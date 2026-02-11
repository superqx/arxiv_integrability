import os
import re
import json
import arxiv
import yaml
import logging
import argparse
import datetime
import requests
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


def get_daily_papers(topic, query, max_results=10, category="cond-mat.stat-mech"):
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

        for result in search_engine.results():
            primary = result.primary_category

            # Simple shortening to ~30 words using only built-ins
            def shorten_to_approx_30_words(text: str, target: int = 30) -> str:
                if not text:
                    return ""
                sentences = text.split('. ')
                result = []
                total_words = 0
                for sent in sentences:
                    words = sent.split()
                    if total_words + len(words) > target and result:
                        break
                    result.append(sent.strip())
                    total_words += len(words)
                    if not sent.endswith('.'):
                        result[-1] += '.'
                shortened = ' '.join(result)
                # Final hard limit
                all_words = shortened.split()
                if len(all_words) > target:
                    shortened = ' '.join(all_words[:target]) + '...'
                return shortened.strip()


            # Only keep if primary category matches what we asked for
            if primary != category:
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

            logging.info(f"Time = {update_time} title = {paper_title} author = {paper_first_author} category = {primary_category}")

            # eg: 2108.09112v1 -> 2108.09112
            ver_pos = paper_id.find('v')
            if ver_pos == -1:
                paper_key = paper_id
            else:
                paper_key = paper_id[0:ver_pos]

            paper_url = arxiv_url + 'abs/' + paper_key

            short_abstract = shorten_to_approx_30_words(paper_abstract)

            if len(paper_abstract) > 30:
                short_abstract += "..."
            # Code link is set to null as PapersWithCode API is deprecated
            # You can optionally enable GitHub search by uncommenting below
            # code_link = get_code_link(paper_title)
            code_link = "null"

            content[paper_key] = (
                f"|**{update_time}** — **{paper_title}**  \n"
                f"{paper_first_author} et al.  \n"
                f"[[arxiv:{paper_key}]({paper_url})]  \n\n"
                f"<details>\n"
                f"<summary>Abstract({len(paper_abstract.split())})</summary>\n\n"
                f"</details>\n\n"
                f"**Short abstract**: {short_abstract}\n\n"
                f"**Code**: {code_link}\n"
            )

            content_to_web[paper_key] = (
                f"- **{update_time}** — **{paper_title}**  \n"
                f"  {paper_first_author} et al.  \n"
                f"  [Paper]({paper_url})  \n"
                f"  **Abstract** (~100 words): {short_abstract}\n"
            )

            # Add comments if available
            if comments != None:
                content_to_web[paper_key] += f", {comments}\n"
            else:
                content_to_web[paper_key] += f"\n"

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
        parts = s.split("|")
        date = parts[1].strip()
        title = parts[2].strip()
        authors = parts[3].strip()
        arxiv_id = parts[4].strip()
        code = parts[5].strip()
        arxiv_id = re.sub(r'v\d+', '', arxiv_id)
        return date, title, authors, arxiv_id, code

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
                update_time, paper_title, paper_first_author, paper_url, code_url = parse_arxiv_string(contents)

                contents = "|{}|{}|{}|{}|{}|\n".format(
                    update_time, paper_title, paper_first_author, paper_url, code_url
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

            f.write("> Usage instructions: [here](./docs/README.md#usage)\n\n")

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
                        f.write("|Publish Date|Title|Authors|PDF|Code|\n" + "|---|---|---|---|---|\n")
                    else:
                        f.write("| Publish Date | Title | Authors | PDF | Code |\n")
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
                category=category
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

    args = parser.parse_args()

    config = load_config(args.config_path)
    config = {**config, 'update_paper_links': args.update_paper_links}

    demo(**config)
