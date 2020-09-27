from route_config import RequestsConfig

class SonarObject:
    def __init__(self, endpoint, params, output_path):
        self.__endpoint = endpoint
        self._params = params
        self._element_list = []
        self.__total_num_elements = 0
        self.__response = {}

        self._route_config = RequestsConfig()
        self.__session = self._route_config.route_session()
        self._output_path = output_path
    
    def _call_api(self):
        return self._route_config.call_api_route(session=self.__session, endpoint=self.__endpoint,
                                            params=self._params)

    def _query_server(self, key):
        response = self._call_api()
        if not self._route_config.check_invalid_status_code(response=response):
            return []
        response_dict = response.json()

        self._element_list = response_dict[key]

        if key == "metrics":
            self.__total_num_elements = response_dict['total']
        else:
            self.__total_num_elements = response_dict['paging']['total']

        if self._more_elements():
            self._params['p'] = self._params['p'] + 1
            self._element_list = self._element_list + self._query_server(key)

        return self._element_list
    
    def _more_elements(self):
        if self._params['p'] * self._params['ps'] < self.__total_num_elements:
            return True
        return False

    def _write_csv(self):
        pass

    def process_elements(self):
        pass