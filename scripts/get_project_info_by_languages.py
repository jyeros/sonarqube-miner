from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter, Retry
import requests
from argparse import ArgumentParser
import json
from urllib.parse import urlencode

parser = ArgumentParser()
parser.add_argument(
        "-c", "--config-file", type=str, help="Path to the search config file", required=True
    )

args = parser.parse_args()

with open(args.config_file, 'r') as f:
    config = json.load(f)

languages = config['languages']
max_workers = config['max_workers']

client = requests.Session()
retries = Retry(total=7, backoff_factor=2)
client.mount('https://', HTTPAdapter(max_retries=retries))

page_size = 500 # 500 is the max page size
max_elements = 10000
base_url = 'https://sonarcloud.io'
project_search_base_url = base_url + '/api/components/search_projects'
repo_info_base_url = base_url + '/api/navigation/component'
metrics_base_url = base_url + '/api/measures/component'
issue_base_url = base_url + '/api/issues/search'
branch_info_base_url = base_url + '/api/project_branches/list'

data = {}

def find_upper_bound(language, lower_bound, upper_bound):
    while True:
        filters = {'ps': 1, 'p': 1, 'filter': f'languages = {language} and ncloc >= {lower_bound} and ncloc < {upper_bound}'}
        response = client.get(f'{project_search_base_url}?{urlencode(filters)}').json()
        if response['paging']['total'] >= max_elements:
            upper_bound = (lower_bound + upper_bound) // 2
        else:
            break
    return upper_bound

def dump_all_data(language, lower_bound, upper_bound):
    i = 1
    more_elements = True
    while more_elements:
        filters = {'ps': page_size, 'p': i, 'filter': f'languages = {language} and ncloc >= {lower_bound}' + (f' and ncloc < {upper_bound}' if upper_bound is not None else '')}
        response = client.get(f'{project_search_base_url}?{urlencode(filters)}').json()
        for component in response['components']:
            data[f'{component["organization"]}/{component["key"]}'] = {'id': component['key'], 'organization': component['organization']}
        if page_size * i > response['paging']['total']:
            more_elements = False
        i += 1
    return response['paging']['total'] != 0

def __add_repo_info(new_data: list, repos: list, project, repo):
    new_data.append(project)
    if repo is not None:
        repos.append(repo)

def __add_metrics(project, metrics=None):
    if metrics is None:
        metrics = ['ncloc', 'ncloc_language_distribution', 'bugs', 'reliability_rating', 'vulnerabilities', 'security_rating', 'security_hotspots', 'security_review_rating', 'security_hotspots_reviewed', 'code_smells', 'sqale_rating', 'coverage', 'duplicated_lines_density']
    filters = {
        'component': project['id'],
        'organization': project['organization'],
        'metricKeys': str.join(',', metrics)
    }
    body = client.get(f'{metrics_base_url}?{urlencode(filters)}').json()
    metrics = body.get('component', {'measures': {}})['measures']

    project['metrics'] = {}
    for metric in metrics:
        if metric['metric'] == 'ncloc_language_distribution':
            project['metrics']['ncloc_by_language'] = {}
            for lang in metric['value'].split(';'):
                lang, count = lang.split('=')
                project['metrics']['ncloc_by_language'][lang] = int(count)
        else:
            project['metrics'][metric['metric']] = metric['value']

def __add_sonarqube_issue_info(project):
    i = 1
    more_elements = True
    project['issues'] = []
    while more_elements:
        filters = {
            'componentKeys': project['id'],
            'organization': project['organization'],
            'ps': page_size,
            'p': i
        }
        body = client.get(f'{issue_base_url}?{urlencode(filters)}').json()
        if body['total'] >= 10000:
            raise Exception(f'Project {project["id"]} has more than 10000 issues. Handle this case.')
        issues = body.get('issues', [])
        project['issues'] += issues
        if page_size * i > body['total']:
            more_elements = False
        i += 1

def __get_repo_info(project, new_data, repos, writing_executor):
    print(f'Getting repo info for {project["organization"]}/{project["id"]}')
    filters = {
        'component': project['id'],
        'organization': project['organization']
    }
    body = client.get(f'{repo_info_base_url}?{urlencode(filters)}').json()
    repoInfo = body.get('alm', None)

    filters = {
        'project': project['id'],
        'organization': project['organization']
    }
    body = client.get(f'{branch_info_base_url}?{urlencode(filters)}').json()
    branches = body.get('branches', [])
    branches = [b for b in branches if b['isMain'] == True]
    commit = branches[0].get('commit', {}).get('sha', None) if len(branches) > 0 else None

    repo = {'full_name': f"{project['organization']}/{project['id']}"}
    if repoInfo is not None and commit is not None:
        project['repo'] = repoInfo['url']
        project['commit_hash'] = commit

        repo['url'] = repoInfo['url']
        repo['commit_hash'] = commit
    else:
        url=f'https://github.com/{project["organization"]}/{project["id"]}'
        if client.get(f'{url}/commit/{commit}').status_code == 200:
            project['repo'] = url
            project['commit_hash'] = commit
            repo['url'] = url
            repo['commit_hash'] = commit

    __add_metrics(project)
    __add_sonarqube_issue_info(project)
    writing_executor.submit(__add_repo_info, new_data, repos, project, repo)

def get_repo_info(data):
    repos = []
    new_data = []
    with ThreadPoolExecutor(max_workers=1) as writing_executor:
            with ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                for project in data.values():
                    executor.submit(
                        __get_repo_info,
                        project,
                        new_data,
                        repos,
                        writing_executor,
                    )

    return new_data, repos

init_upper_bound = 100000

for language in languages:
    lower_bound = 0
    more_elements = True
    data = {}
    print(f'Processing {language}...')
    while more_elements:
        upper_bound = find_upper_bound(language, lower_bound, init_upper_bound)
        print(f'Processing {language} with lower bound {lower_bound} and upper bound {upper_bound}...')
        more_elements = dump_all_data(language, lower_bound, upper_bound)
        lower_bound = upper_bound

    # Dump the rest of the data
    print(f'Processing {language} with lower bound {lower_bound}...')
    dump_all_data(language, lower_bound=init_upper_bound, upper_bound=None)

    print(f'Getting repo info for {language}...')
    projects, repos = get_repo_info(data)

    print(f'Writing {language} data to file...')
    with open(f'projects_{language}.json', 'w') as f:
        f.write(json.dumps(projects))

    print(f'Writing {language} repos to file...')
    with open(f'repos_{language}.json', 'w') as f:
        f.write(json.dumps(repos))
