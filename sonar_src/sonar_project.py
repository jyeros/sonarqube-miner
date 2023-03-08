import pandas as pd
from pathlib import Path
import requests

from .sonar_object import SonarObject
from .route_config import RequestsConfig

class Projects(SonarObject):
    def __init__(self, server, organization, output_path):
        self._server = server
        self._organization = organization
        SonarObject.__init__(
            self,
            endpoint = server + "api/components/search",
            params =    {
                'p': 1,     # page/iteration
                'ps': 100,  # pageSize
                'organization': organization,
                'qualifiers': 'TRK'
            },
            output_path = output_path
        )

    def _write_csv(self):
        projects = []
        for project in self._element_list:
            project_var = (project.values())
            projects.append(project_var)

        if projects:
            headers = list(self._element_list[0].keys())
            output_path = Path(self._output_path).joinpath("projects")
            output_path.mkdir(parents=True, exist_ok=True)
            file_path = output_path.joinpath("projects.csv")
            df = pd.DataFrame(data=projects, columns=headers)
            df.to_csv(file_path, index=False, header=True, mode='w')

    def _query_repo_server(self):
        projects = [p for p in self._element_list]
        new_projects = []
        no_repo = []
        repos = []
        for project in projects:
            r = self._route_config.call_api_route(session=self._SonarObject__session, endpoint=self._server + "api/navigation/component", params={
                'component': project['key'],
                'organization': project['organization']
            })
            body = r.json()
            repoInfo = body.get('alm', None)

            r = self._route_config.call_api_route(session=self._SonarObject__session, endpoint=self._server + "api/project_branches/list", params={
                'project': project['key'],
                'organization': project['organization']
            })
            body = r.json()
            branches = body.get('branches', [])
            branches = [b for b in branches if b['isMain'] == True]
            commit = branches[0].get('commit', {}).get('sha', None) if len(branches) > 0 else None

            if repoInfo is not None and commit is not None:
                project['repo'] = repoInfo['url']

                repos.append({'full_name': f"{project['organization']}/{project['key']}", 'url': repoInfo['url'], 'commit_hash': commit})

                new_projects.append(project)

            else:
                repo = f'https://github.com/{project["organization"]}/{project["key"]}'
                if requests.get(f'{repo}/commit/{commit}').status_code == 200:
                    project['repo'] = repo
                    repos.append({'full_name': f"{project['organization']}/{project['key']}", 'url': repo, 'commit_hash': commit})
                    new_projects.append(project)
                else:
                    no_repo.append(project)
        self._element_list = new_projects
        import json
        with open(Path(self._output_path).joinpath("repos.json"), 'w') as f:
            json.dump(repos, f)

    def process_elements(self):
        self._query_server(key = "components")
        self._query_repo_server()
        self._write_csv()
        return self._element_list