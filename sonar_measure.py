from collections import OrderedDict
import pandas as pd
import os, sys, csv
from datetime import datetime
from pathlib import Path
from sonar_object import SonarObject
from route_config import RequestsConfig

def safe_cast(val, to_type, contain_comma=False, list_with_semicolon=False):
    if to_type in ['INT', 'WORK_DUR']:
        try:
            return int(val)
        except (ValueError, TypeError):
            print("WARNING: exception casting value {0} to type {1}".format(str(val), to_type))
            return None
    elif to_type in ['FLOAT', 'PERCENT', 'RATING']:
        try:
            return float(val)
        except (ValueError, TypeError):
            print("WARNING: exception casting value {0} to type {1}".format(str(val), to_type))
            return None
    elif to_type == 'BOOL':
        try:
            return bool(val)
        except (ValueError, TypeError):
            print("WARNING: exception casting value {0} to type {1}".format(str(val), to_type))
            return None
    elif to_type == 'MILLISEC':
        try:
            if len(val) >= 12:
                return datetime.fromtimestamp(int(val) / 1000)
            else:
                return int(val)
        except (ValueError, TypeError):
            print("WARNING: exception casting value {0} to type {1}".format(str(val), to_type))
            return None
    else:
        try:
            value = str(val)
            if contain_comma:
                value = value.replace(',', ';')
            if list_with_semicolon:
                value = value.replace(';', ',')
            return value
        except (ValueError, TypeError):
            print("ERROR: error casting to type {0}".format(to_type))
            return None

def concat_measures(measures_1, measures_2):
    for measure_1, measure_2 in zip(measures_1, measures_2):
        if measure_2['history']:
            measure_1['history'] = measure_1['history'] + measure_2['history']
    return measures_1

def read_metrics(output_path):
    path = f'{output_path}/metrics/metrics.csv'
    p = Path(path)
    if not p.exists():
        print("ERROR: Path for metrics {0} does not exists.".format(p.resolve()))
        sys.exit(1)
    try:
        metrics_order = {}
        with open(p, 'r') as f:
            csv_reader = csv.reader(f)
            next(csv_reader)
            order = 0
            for line in csv_reader:
                metric = line[1]
                metric_type = line[2]
                metrics_order[metric] = (order, metric_type)
                order += 1
        return metrics_order
    except Exception as e:
        print("ERROR: Reading metrics file", e)
        sys.exit(1)

class Measures(SonarObject):
    def __init__(self, server, output_path, project_key, analysis_keys):
        SonarObject.__init__(
            self,
            endpoint = server + "api/measures/search_history",
            params =    {
                'p': 1,     # page/iteration
                'ps': 1000,  # pageSize
                'component': project_key
            },
            output_path = output_path
        )
        self.__columns = []
        self.__data = {}
        self.__project_key = project_key
        self.__analysis_keys = analysis_keys

    # Different implementation from superclass method at line
    # meansures = concat_meansures(meansires, self._query_server)
    def _query_server(self):
        response = self._call_api()
        if not self._route_config.check_invalid_status_code(response=response):
            return []

        response_dict = response.json()
        measures = response_dict["measures"]
        self.__total_num_measures = response_dict['paging']['total']

        if self._more_elements():
            self._params['p'] = self._params['p'] + 1
            measures = concat_measures(measures, self._query_server())
        return measures

    def __extract_measures_value(self, measures, metrics_order_type):

        num_rows = len(self.__analysis_keys)

        data = OrderedDict()
        data['project_key'] = [self.__project_key] * num_rows
        data['analysis_key'] = self.__analysis_keys

        columns = ['project_key', 'analysis_key']

        for measure in measures:
            metric = measure['metric']

            metric_type = metrics_order_type[metric][1]
            columns.append(metric)
            history = measure['history']

            contain_comma = False
            if metric in ['quality_profiles', 'quality_gate_details']:
                contain_comma = True

            list_with_semicolon = False
            if metric in ['class_complexity_distribution', 'function_complexity_distribution',
                          'file_complexity_distribution', 'ncloc_language_distribution']:
                list_with_semicolon = True

            values = list(map(lambda x: None if 'value' not in x else safe_cast(x['value'], metric_type, contain_comma, list_with_semicolon), history))
            values.reverse()            
            values = values[:num_rows]  # get only num_rows latest values

            if len(values) < num_rows:
                values = values + [None] * (num_rows - len(values))

            if metrics_order_type[metric][1] == "INT":
                values = pd.array(values, dtype=pd.Int64Dtype())

            data[metric] = values
        return columns, data

    def _write_csv(self):
        output_path = Path(self._output_path).joinpath("measures")
        output_path.mkdir(parents=True, exist_ok=True)
        file_name = self.__project_key.replace(' ', '_').replace(':', '_')
        file_path = output_path.joinpath(f"{file_name}.csv")

        df = pd.DataFrame(data=self.__data, columns=self.__columns)
        df.to_csv(file_path, index=False, header=True)

    def __metric_wise_search(self):
        metrics_order_type = read_metrics(self._output_path)
        metrics_list = list(metrics_order_type.keys())
        measures = []

        for i in range(0, len(metrics_list), 10):
            self._params['metrics'] = ','.join(metrics_list[i:i + 10])
            self._params['p'] = 1
            measures = measures + self._query_server()

        measures.sort(key=lambda x: metrics_order_type[x['metric']][0])

        self.__columns, self.__data = self.__extract_measures_value(measures, metrics_order_type)
        
    def process_elements(self):
        self.__metric_wise_search()
        self._write_csv()
