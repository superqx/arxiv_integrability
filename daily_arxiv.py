import os
import re
import json
import arxiv
import yaml
import logging
import argparse
import datetime
import requests
from typing import List, Optional
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from datetime import timedelta

logging.basicConfig(
    format='[%(asctime)s %(levelname)s] %(message)s',
    datefmt='%m/%d/%Y %H:%M:%S',
    level=logging.INFO
)

github_url = "https://api.github.com/search/repositories"
arxiv_url = "https://arxiv.org/"

try:
    import pdfplumber  # type: ignore
except Exception:
    pdfplumber = None

SUMMARY_MAX_WORDS = 120
SUMMARY_TARGET_SENTENCES = 3
SUMMARY_MIN_WORDS = 60
SUMMARY_MAX_CHARS = 8000


def get_deepseek_api_key() -> Optional[str]:
    return os.environ.get("DEEPSEEK_API_KEY")


def deepseek_summarize(text: str, title: str, session: requests.Session,
                       base_url: str, model: str, max_tokens: int,
                       temperature: Optional[float], language: str) -> str:
    if not text:
        return ""
    lang_instruction = "Write the summary in Chinese." if language.lower().startswith("zh") else "Write the summary in English."
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You write concise, factual paper summaries."},
            {"role": "user", "content": (
                "Summarize the paper in 3-4 sentences. Focus on: problem, method, key results, "
                "and significance. Avoid copying the abstract. "
                f"{lang_instruction}\n\n"
                f"Title: {title}\n\n"
                f"Paper text:\n{text}"
            )}
        ],
        "max_tokens": max_tokens,
        "stream": False
    }
    if temperature is not None:
        payload["temperature"] = temperature

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {get_deepseek_api_key()}",
        "Content-Type": "application/json"
    }

    try:
        resp = session.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logging.warning(f"DeepSeek summarization failed: {e}")
        return ""


def create_session():
    """Create a requests session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Add user agent to avoid blocking
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (compatible; ArXiv-Daily-Collector/1.0; +https://github.com/superqx/arxiv_integrability)'
    })
    return session


def load_config(config_file: str) -> dict:
    """
    Load configuration file

    Args:
        config_file: input config file path

    Returns:
        a dict of configuration
    """
    def pretty_filters(**config) -> dict:
        """Parse filters from config"""
        keywords = dict()
        EXCAPE = '\"'
        QUOTA = ''
        OR = ' OR '

        def parse_filters(filters: list) -> str:
            ret = ''
            for idx in range(0, len(filters)):
                filter_item = filters[idx]
                if len(filter_item.split()) > 1:
                    ret += (EXCAPE + filter_item + EXCAPE)
                else:
                    ret += (QUOTA + filter_item + QUOTA)
                if idx != len(filters) - 1:
                    ret += OR
            return ret

        for k, v in config['keywords'].items():
            # Handle both old and new config format
            if isinstance(v, dict) and 'filters' in v:
                # Handle category as both string and list
                category = v.get('category', 'cond-mat.stat-mech')
                if isinstance(category, list):
                    category = category[0] if category else 'cond-mat.stat-mech'

                keywords[k] = {
                    'query': parse_filters(v['filters']),
                    'category': category
                }
            else:
                # Old format compatibility
                keywords[k] = {
                    'query': parse_filters(v),
                    'category': 'cond-mat.stat-mech'
                }
        return keywords

    with open(config_file, 'r') as f:
        config = yaml.load(f, Loader=yaml.FullLoader)

    config['kv'] = pretty_filters(**config)
    logging.info(f'config = {config}')

    return config


def get_authors(authors, first_author=False):
    """Get author names from arxiv result"""
    output = str()
    if first_author == False:
        output = ", ".join(str(author) for author in authors)
    else:
        output = authors[0]
    return output


def sort_papers(papers):
    """Sort papers by date"""
    output = dict()
    keys = list(papers.keys())
    keys.sort(reverse=True)
    for key in keys:
        output[key] = papers[key]
    return output


def get_code_link(qword: str, session=None) -> str:
    """
    Search for code repository on GitHub

    Args:
        qword: query string, eg. arxiv ids and paper titles
        session: requests session with retry logic

    Returns:
        paper_code in github: string, if not found, return None
    """
    query = f"{qword}"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc"
    }

    try:
        if session:
            r = session.get(github_url, params=params, timeout=10)
        else:
            r = requests.get(github_url, params=params, timeout=10)

        results = r.json()
        code_link = None

        if results.get("total_count", 0) > 0:
            code_link = results["items"][0]["html_url"]

        return code_link
    except Exception as e:
        logging.warning(f"Error fetching code link: {e}")
        return None


def shorten_to_approx_words(text: str, target: int = 60) -> str:
    if not text:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    result = []
    total_words = 0
    for sent in sentences:
        words = sent.split()
        if total_words + len(words) > target and result:
            break
        result.append(sent.strip())
        total_words += len(words)
    shortened = ' '.join(result)
    all_words = shortened.split()
    if len(all_words) > target:
        shortened = ' '.join(all_words[:target]) + '...'
    if shortened and not shortened.endswith(('.', '!', '?')):
        shortened += '.'
    return shortened.strip()


def ensure_pdf_dir(store_pdfs: bool, output_dir: Optional[str]) -> str:
    if store_pdfs:
        pdf_dir = output_dir or os.path.join(os.path.dirname(__file__), "output", "pdfs")
    else:
        pdf_dir = os.path.join(os.path.dirname(__file__), "tmp", "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    return pdf_dir


def download_pdf(paper_key: str, session: requests.Session, store_pdfs: bool,
                 output_dir: Optional[str]) -> Optional[str]:
    pdf_dir = ensure_pdf_dir(store_pdfs, output_dir)
    pdf_path = os.path.join(pdf_dir, f"{paper_key}.pdf")
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return pdf_path
    pdf_url = f"{arxiv_url}pdf/{paper_key}.pdf"
    try:
        resp = session.get(pdf_url, timeout=20)
        resp.raise_for_status()
        with open(pdf_path, "wb") as f:
            f.write(resp.content)
        return pdf_path
    except Exception as e:
        logging.warning(f"Failed to download PDF for {paper_key}: {e}")
        return None


def extract_pdf_text(pdf_path: str) -> str:
    if pdfplumber is None:
        return ""
    try:
        text_chunks = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    text_chunks.append(page_text)
        return "\n".join(text_chunks)
    except Exception as e:
        logging.warning(f"Failed to extract text from PDF {pdf_path}: {e}")
        return ""


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]


def select_section(text: str, start_keys: List[str], end_keys: List[str]) -> str:
    lower = text.lower()
    start_idx = None
    end_idx = None
    for key in start_keys:
        idx = lower.find(key)
        if idx != -1 and (start_idx is None or idx < start_idx):
            start_idx = idx
    if start_idx is None:
        return ""
    for key in end_keys:
        idx = lower.find(key, start_idx + 1)
        if idx != -1 and (end_idx is None or idx < end_idx):
            end_idx = idx
    return text[start_idx:end_idx] if end_idx else text[start_idx:]


def score_sentences(sentences: List[str]) -> List[int]:
    stopwords = {
        "the", "and", "of", "to", "a", "in", "for", "is", "on", "we", "this", "that",
        "with", "as", "are", "by", "an", "be", "from", "our", "at", "it", "these",
        "their", "which", "or", "can", "also", "have", "has", "using"
    }
    word_freq = {}
    for sent in sentences:
        for w in re.findall(r"[A-Za-z']+", sent.lower()):
            if w in stopwords or len(w) <= 2:
                continue
            word_freq[w] = word_freq.get(w, 0) + 1
    scores = []
    for sent in sentences:
        score = 0
        for w in re.findall(r"[A-Za-z']+", sent.lower()):
            score += word_freq.get(w, 0)
        scores.append(score)
    return scores


def summarize_text(text: str) -> str:
    if not text:
        return ""
    intro = select_section(text, ["introduction"], ["conclusion", "discussion", "references"])
    concl = select_section(text, ["conclusion", "discussion", "summary"], ["references"])
    candidate = (intro + "\n" + concl).strip()

    if len(candidate) < 200:
        candidate = text

    sentences = split_sentences(candidate)
    if not sentences:
        return ""

    scores = score_sentences(sentences)
    ranked = sorted(range(len(sentences)), key=lambda i: scores[i], reverse=True)

    picked = []
    total_words = 0
    for idx in ranked:
        sent = sentences[idx]
        sent_words = len(sent.split())
        if total_words + sent_words > SUMMARY_MAX_WORDS and picked:
            continue
        picked.append((idx, sent))
        total_words += sent_words
        if len(picked) >= SUMMARY_TARGET_SENTENCES or total_words >= SUMMARY_MAX_WORDS:
            break

    if not picked:
        return ""

    picked.sort(key=lambda x: x[0])
    summary = " ".join(s for _, s in picked).strip()
    if summary and not summary.endswith(('.', '!', '?')):
        summary += '.'
    return summary


def build_paper_summary(paper_key: str, paper_title: str, paper_abstract: str,
                        session: requests.Session, store_pdfs: bool,
                        output_dir: Optional[str], use_deepseek: bool,
                        deepseek_base_url: str, deepseek_model: str,
                        deepseek_max_tokens: int,
                        deepseek_temperature: Optional[float],
                        summary_language: str) -> str:
    def is_garbled(text: str) -> bool:
        if not text:
            return True
        letters = re.findall(r"[A-Za-z]", text)
        ratio = len(letters) / max(1, len(text))
        if ratio < 0.2:
            return True
        lower = text.lower()
        if "<latexit" in lower or "cid:" in lower:
            return True
        if "�" in text:
            return True
        return False

    if pdfplumber is None:
        logging.warning("pdfplumber not available; falling back to abstract-based summary")
        return shorten_to_approx_words(paper_abstract, target=SUMMARY_MIN_WORDS)

    pdf_path = download_pdf(paper_key, session, store_pdfs, output_dir)
    if not pdf_path:
        return shorten_to_approx_words(paper_abstract, target=SUMMARY_MIN_WORDS)

    full_text = extract_pdf_text(pdf_path)
    full_text = re.sub(r"\s+", " ", full_text).strip()

    candidate_text = ""
    if full_text and len(full_text) >= 1000 and not is_garbled(full_text):
        candidate_text = full_text[:SUMMARY_MAX_CHARS]
    else:
        candidate_text = paper_abstract or full_text

    api_key = get_deepseek_api_key()
    if use_deepseek and not api_key:
        logging.warning("DEEPSEEK_API_KEY not set; falling back to non-LLM summary.")

    if use_deepseek and api_key:
        ds_summary = deepseek_summarize(
            candidate_text,
            paper_title,
            session,
            base_url=deepseek_base_url,
            model=deepseek_model,
            max_tokens=deepseek_max_tokens,
            temperature=deepseek_temperature,
            language=summary_language
        )
        if ds_summary:
            return ds_summary

    summary = summarize_text(full_text)
    if summary and len(summary.split()) >= SUMMARY_MIN_WORDS and not is_garbled(summary):
        return summary

    fallback = shorten_to_approx_words(paper_abstract, target=SUMMARY_MIN_WORDS)
    if summary_language.lower().startswith("zh") and fallback:
        return f"（中文摘要生成失败，以下为英文摘要压缩）{fallback}"
    return fallback

def get_daily_papers(topic, query, max_results=10, category="cond-mat.stat-mech",
                     days_back: int = 1, store_pdfs: bool = False,
                     pdf_output_dir: Optional[str] = None,
                     end_date: Optional[datetime.date] = None,
                     use_deepseek: bool = False,
                     deepseek_base_url: str = "https://api.deepseek.com",
                     deepseek_model: str = "deepseek-chat",
                     deepseek_max_tokens: int = 256,
                     deepseek_temperature: Optional[float] = None,
                     use_published_date: bool = False,
                     date_tz_offset_hours: int = 0,
                     include_ids: Optional[List[str]] = None,
                     summary_language: str = "en",
                     summary_languages: Optional[List[str]] = None):
    """
    Get daily papers from arXiv

    Args:
        topic: str - topic name
        query: str - search query
        max_results: int - maximum number of results
        category: str - arXiv category (e.g., "physics", "physics.optics", "cs")

    Returns:
        paper_with_code: dict
    """
    content = dict()
    content_to_web = dict()

    # Add category filter to the query
    if category:
        query_with_category = f"{query} AND cat:{category}"
    else:
        query_with_category = query

    logging.info(f"Searching with query: {query_with_category}")

    try:
        search_engine = arxiv.Search(
            query=query_with_category,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate
        )

        session = create_session()
        if end_date is None:
            end_date = datetime.date.today()
        start_date = end_date - timedelta(days=days_back - 1)

        include_set = set(include_ids or [])

        def category_matches(primary_cat: str, requested_cat: str) -> bool:
            if primary_cat == requested_cat:
                return True
            # If requested is a broad category (no dot), accept subcategories.
            if "." not in requested_cat and primary_cat.startswith(requested_cat + "."):
                return True
            return False

        for result in search_engine.results():
            primary = result.primary_category

            # Only keep if primary category matches what we asked for
            if not category_matches(primary, category):
                logging.info(f"Skipping {result.get_short_id()} - primary category {primary} != requested {category}")
                continue

            paper_id = result.get_short_id()
            paper_title = result.title
            paper_url = result.entry_id
            paper_abstract = result.summary.replace("\n", " ").strip()
            paper_authors = get_authors(result.authors)
            paper_first_author = get_authors(result.authors, first_author=True)
            primary_category = result.primary_category
            publish_time = result.published.date()
            update_time = result.updated.date()
            comments = result.comment

            # eg: 2108.09112v1 -> 2108.09112
            ver_pos = paper_id.find('v')
            if ver_pos == -1:
                paper_key = paper_id
            else:
                paper_key = paper_id[0:ver_pos]

            raw_dt = result.published if use_published_date else result.updated
            if raw_dt.tzinfo is None:
                raw_dt = raw_dt.replace(tzinfo=datetime.timezone.utc)
            local_dt = raw_dt + datetime.timedelta(hours=date_tz_offset_hours)
            filter_date = local_dt.date()

            logging.info(
                f"Time = {filter_date} (raw={raw_dt.isoformat()}) title = {paper_title} "
                f"author = {paper_first_author} category = {primary_category}"
            )

            # Keep only papers updated within the date window (inclusive)
            if paper_key in include_set:
                logging.info(f"Including {paper_key} via include_ids override")
            elif filter_date < start_date or filter_date > end_date:
                logging.info(
                    f"Skipping {result.get_short_id()} - updated {filter_date} outside "
                    f"window {start_date} to {end_date}"
                )
                continue

            paper_url = arxiv_url + 'abs/' + paper_key

            requested_langs = summary_languages or [summary_language]
            summary_lang = "en" if "en" in requested_langs else requested_langs[0]
            summary_en = build_paper_summary(
                paper_key,
                paper_title,
                paper_abstract,
                session,
                store_pdfs=store_pdfs,
                output_dir=pdf_output_dir,
                use_deepseek=use_deepseek,
                deepseek_base_url=deepseek_base_url,
                deepseek_model=deepseek_model,
                deepseek_max_tokens=deepseek_max_tokens,
                deepseek_temperature=deepseek_temperature,
                summary_language=summary_lang
            )
            summary_en = summary_en.replace("\n", " ").replace("|", "/")
            # Code link is set to null as PapersWithCode API is deprecated
            # You can optionally enable GitHub search by uncommenting below
            # code_link = get_code_link(paper_title)
            code_link = "null"

            content[paper_key] = (
                f"|**{publish_time}**|**{paper_title}**|{paper_authors}|"
                f"[[arxiv:{paper_key}]({paper_url})]|{summary_en}|\n"
            )

            content_to_web[paper_key] = (
                f"|**{publish_time}**|**{paper_title}**|{paper_authors}|"
                f"[arXiv]({paper_url})|{summary_en}|\n"
            )

    except Exception as e:
        logging.error(f"Error fetching papers for topic {topic}: {e}")

    data = {topic: content}
    data_web = {topic: content_to_web}

    return data, data_web


def update_paper_links(filename):
    """
    Weekly update paper links in json file
    """
    def parse_arxiv_string(s):
        parts = [p.strip() for p in s.split("|") if p.strip()]
        date = parts[0] if len(parts) > 0 else ""
        title = parts[1] if len(parts) > 1 else ""
        authors = parts[2] if len(parts) > 2 else ""
        arxiv_id = parts[3] if len(parts) > 3 else ""
        summary = parts[4] if len(parts) > 4 else ""
        arxiv_id = re.sub(r'v\d+', '', arxiv_id)
        return date, title, authors, arxiv_id, summary

    try:
        with open(filename, "r") as f:
            content = f.read()

        if not content:
            m = {}
        else:
            m = json.loads(content)

        json_data = m.copy()

        for keywords, v in json_data.items():
            logging.info(f'keywords = {keywords}')
            for paper_id, contents in v.items():
                contents = str(contents)
                update_time, paper_title, paper_first_author, paper_url, summary = parse_arxiv_string(contents)

                contents = (
                    f"### {paper_title}\n\n"
                    f"- **Date**: {update_time}\n"
                    f"- **Authors**: {paper_first_author} et al.\n"
                    f"- **arXiv**: [{paper_url.split('/')[-1]}]({paper_url})\n"
                    f"- **Summary**: {summary}\n"
                    "\n"
                )
                json_data[keywords][paper_id] = str(contents)

                logging.info(f'paper_id = {paper_id}, contents = {contents}')
                # PapersWithCode API is deprecated, skip code link updates
                logging.info(f'Skipping code link update for paper_id = {paper_id} (PapersWithCode API deprecated)')

        # dump to json file
        with open(filename, "w") as f:
            json.dump(json_data, f)

    except Exception as e:
        logging.error(f"Error updating paper links: {e}")


def update_json_file(filename, data_dict):
    """
    Daily update json file using data_dict
    """
    try:
        with open(filename, "r") as f:
            content = f.read()

        if not content:
            m = {}
        else:
            m = json.loads(content)

        json_data = m.copy()

        # update papers in each keywords
        for data in data_dict:
            for keyword in data.keys():
                papers = data[keyword]
                if keyword in json_data.keys():
                    json_data[keyword].update(papers)
                else:
                    json_data[keyword] = papers

        with open(filename, "w") as f:
            json.dump(json_data, f)

    except Exception as e:
        logging.error(f"Error updating JSON file: {e}")


def json_to_md(filename, md_filename, task='', to_web=False, use_title=True,
               use_tc=True, show_badge=True, use_b2t=True):
    """
    Convert JSON file to Markdown

    Args:
        filename: str - input JSON file
        md_filename: str - output Markdown file
        task: str - task description
        to_web: bool - whether generating for web
        use_title: bool - whether to use title
        use_tc: bool - whether to use table of contents
        show_badge: bool - whether to show badges
        use_b2t: bool - whether to use back-to-top links
    """
    def pretty_math(s: str) -> str:
        """Format mathematical expressions"""
        ret = ''
        match = re.search(r"\$.*\$", s)
        if match == None:
            return s

        math_start, math_end = match.span()
        space_trail = space_leading = ''

        if s[:math_start][-1] != ' ' and '*' != s[:math_start][-1]:
            space_trail = ' '
        if s[math_end:][0] != ' ' and '*' != s[math_end:][0]:
            space_leading = ' '

        ret += s[:math_start]
        ret += f'{space_trail}${match.group()[1:-1].strip()}${space_leading}'
        ret += s[math_end:]

        return ret

    DateNow = datetime.date.today()
    DateNow = str(DateNow)
    DateNow = DateNow.replace('-', '.')

    try:
        with open(filename, "r") as f:
            content = f.read()

        if not content:
            data = {}
        else:
            data = json.loads(content)

        # clean README.md if daily already exist else create it
        with open(md_filename, "w+", encoding="utf-8", newline="\n") as f:
            pass

        # write data into README.md
        with open(md_filename, "a+", encoding="utf-8", newline="\n") as f:
            if (use_title == True) and (to_web == True):
                f.write("---\n" + "layout: default\n" + "---\n\n")

            if use_title == True:
                f.write("## Updated on " + DateNow + "\n")
            else:
                f.write("> Updated on " + DateNow + "\n")

            f.write("> Usage instructions: [here](./docs/USAGE.md#usage)\n\n")

            # Add: table of contents
            if use_tc == True:
                f.write("<details>\n")
                f.write("  <summary>Table of Contents</summary>\n")
                f.write("  <ol>\n")
                for keyword in data.keys():
                    day_content = data[keyword]
                    if not day_content:
                        continue
                    kw = keyword.replace(' ', '-')
                    f.write(f"    <li><a href=#{kw}>{keyword}</a></li>\n")
                f.write("  </ol>\n")
                f.write("</details>\n\n")

            for keyword in data.keys():
                day_content = data[keyword]
                if not day_content:
                    continue

                # the head of each part
                f.write(f"## {keyword}\n\n")

                if use_title == True:
                    if to_web == False:
                        f.write("|Publish Date|Title|Authors|arXiv|Summary|\n" + "|---|---|---|---|---|\n")
                    else:
                        f.write("| Publish Date | Title | Authors | arXiv | Summary |\n")
                        f.write("|:---------|:-----------------------|:---------|:------|:------|\n")

                # sort papers by date
                day_content = sort_papers(day_content)

                for _, v in day_content.items():
                    if v is not None:
                        f.write(pretty_math(v))  # make latex pretty

                f.write(f"\n")

                # Add: back to top
                if use_b2t:
                    top_info = f"#Updated on {DateNow}"
                    top_info = top_info.replace(' ', '-').replace('.', '')
                    f.write(f"<p align=right>(<a href={top_info}>back to top</a>)</p>\n\n")

        logging.info(f"{task} finished")

    except Exception as e:
        logging.error(f"Error converting JSON to Markdown: {e}")


def demo(**config):
    """
    Main function to collect and organize papers
    """
    data_collector = []
    data_collector_web = []

    keywords = config['kv']
    max_results = config['max_results']
    publish_readme = config['publish_readme']
    publish_gitpage = config['publish_gitpage']
    publish_wechat = config['publish_wechat']
    show_badge = config['show_badge']
    b_update = config['update_paper_links']
    days_back = int(config.get('days_back', 1))
    store_pdfs = bool(config.get('store_pdfs', False))
    pdf_output_dir = config.get('pdf_output_dir')
    use_deepseek = bool(config.get('use_deepseek', False))
    deepseek_base_url = config.get('deepseek_base_url', 'https://api.deepseek.com')
    deepseek_model = config.get('deepseek_model', 'deepseek-chat')
    deepseek_max_tokens = int(config.get('deepseek_max_tokens', 256))
    deepseek_temperature = config.get('deepseek_temperature')
    use_published_date = bool(config.get('use_published_date', False))
    date_tz_offset_hours = int(config.get('date_tz_offset_hours', 0))
    include_ids = config.get('include_ids', [])
    summary_language = config.get('summary_language', 'en')
    summary_languages = config.get('summary_languages')
    date_override = config.get('date_override')
    end_date = None
    if date_override:
        try:
            end_date = datetime.datetime.strptime(date_override, "%Y-%m-%d").date()
        except Exception:
            logging.warning(f"Invalid date_override format: {date_override} (expected YYYY-MM-DD)")

    logging.info(f'Update Paper Link = {b_update}')

    if config['update_paper_links'] == False:
        logging.info(f"GET daily papers begin")

        for topic, keyword_config in keywords.items():
            logging.info(f"Topic: {topic}")

            # Extract query and category from config
            query = keyword_config['query']
            category = keyword_config.get('category', 'cond-mat.stat-mech')

            logging.info(f"Category: {category}")

            data, data_web = get_daily_papers(
                topic,
                query=query,
                max_results=max_results,
                category=category,
                days_back=days_back,
                store_pdfs=store_pdfs,
                pdf_output_dir=pdf_output_dir,
                end_date=end_date,
                use_deepseek=use_deepseek,
                deepseek_base_url=deepseek_base_url,
                deepseek_model=deepseek_model,
                deepseek_max_tokens=deepseek_max_tokens,
                deepseek_temperature=deepseek_temperature,
                use_published_date=use_published_date,
                date_tz_offset_hours=date_tz_offset_hours,
                include_ids=include_ids,
                summary_language=summary_language,
                summary_languages=summary_languages
            )

            data_collector.append(data)
            data_collector_web.append(data_web)

        print("\n")
        logging.info(f"GET daily papers end")

    # 1. update README.md file
    if publish_readme:
        json_file = config['json_readme_path']
        md_file = config['md_readme_path']

        if config['update_paper_links']:
            update_paper_links(json_file)
        else:
            update_json_file(json_file, data_collector)
            json_to_md(json_file, md_file, task='Update Readme', show_badge=show_badge)

    # 2. update docs/index.md file (to gitpage)
    if publish_gitpage:
        json_file = config['json_gitpage_path']
        md_file = config['md_gitpage_path']

        if config['update_paper_links']:
            update_paper_links(json_file)
        else:
            update_json_file(json_file, data_collector)
            json_to_md(json_file, md_file, task='Update GitPage',
                      to_web=True, show_badge=show_badge,
                      use_tc=False, use_b2t=False)

    # 3. Update docs/wechat.md file
    if publish_wechat:
        json_file = config['json_wechat_path']
        md_file = config['md_wechat_path']

        if config['update_paper_links']:
            update_paper_links(json_file)
        else:
            update_json_file(json_file, data_collector_web)
            json_to_md(json_file, md_file, task='Update Wechat',
                      to_web=False, use_title=False, show_badge=show_badge)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config_path', type=str, default='config.yaml',
                       help='configuration file path')
    parser.add_argument('--update_paper_links', default=False, action="store_true",
                       help='whether to update paper links etc.')
    parser.add_argument('--days_back', type=int, default=None,
                       help='number of days to include (overrides config)')
    parser.add_argument('--date', type=str, default=None,
                       help='end date in YYYY-MM-DD (overrides config)')
    parser.add_argument('--tz_offset', type=int, default=None,
                       help='timezone offset hours for date filtering (e.g., 8 for UTC+8)')
    parser.add_argument('--use_published_date', action='store_true',
                       help='filter by published date instead of updated date')
    parser.add_argument('--include_id', action='append', default=None,
                       help='arXiv ID to always include (can be repeated)')
    parser.add_argument('--summary_language', type=str, default=None,
                       help='summary language (e.g., en, zh)')

    args = parser.parse_args()

    config = load_config(args.config_path)
    config = {**config, 'update_paper_links': args.update_paper_links}
    if args.days_back is not None:
        config['days_back'] = args.days_back
    if args.date:
        config['date_override'] = args.date
    if args.tz_offset is not None:
        config['date_tz_offset_hours'] = args.tz_offset
    if args.use_published_date:
        config['use_published_date'] = True
    if args.include_id:
        existing = config.get('include_ids', [])
        config['include_ids'] = list(set(existing + args.include_id))
    if args.summary_language:
        config['summary_language'] = args.summary_language

    demo(**config)
