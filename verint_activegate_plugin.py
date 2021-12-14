import json
import xmltodict
import requests
from datetime import datetime
from ruxit.api.base_plugin import RemoteBasePlugin
import logging

logger = logging.getLogger(__name__)

class VerintPluginRemote(RemoteBasePlugin):
    def initialize(self, **kwargs):
        config = kwargs['config']
        logger.info("Config: %s", config)
        self.url = config["url"]
        self.username = config["username"]
        self.password = config["password"]
        self.project_id = config["project_id"]
        self.token = config["token"]
        self.dt_url = config["dt_url"]

    def query(self, **kwargs):

        jsonHeaders = {'Content-Type': 'text/xml'}

        login_data = "<?xml version=\"1.0\" encoding=\"utf-8\"?><soap:Envelope xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body><Login xmlns=\"http://www.perseus.com/Pdc.WS\"><userName>" + self.username + "</userName><password>" + self.password + "</password></Login></soap:Body></soap:Envelope>"
        survey_summary_data = "<?xml version=\"1.0\" encoding=\"utf-8\"?><soap:Envelope xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body><GetSurveyInformation xmlns=\"http://www.perseus.com/Pdc.WS\"><projectId>" + self.project_id + "</projectId></GetSurveyInformation></soap:Body></soap:Envelope>"
        survey_details_data = "<?xml version=\"1.0\" encoding=\"utf-8\"?><soap:Envelope xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body><GetSurveyData xmlns=\"http://www.perseus.com/Pdc.WS\"><projectId>" + self.project_id + "</projectId></GetSurveyData></soap:Body></soap:Envelope>"

        login = requests.post(self.url, data=login_data, headers=jsonHeaders, verify=True)

        surveyJsonHeaders = {'Content-Type': 'text/xml', 'Host': 'efmpreview.verintefm.com', 'Cookie': ''}
        cookieHeader = ''

        for cookie in login.cookies:
            cookieHeader += cookie.name + "=" + cookie.value + ";"

        logger.info(str(login.status_code))

        surveyJsonHeaders['Cookie'] = cookieHeader

        survey_summary = requests.post(self.url, data=survey_summary_data, headers=surveyJsonHeaders, verify=True)

        survey_overview_dict = xmltodict.parse(survey_summary.content.decode())
        survey_overview_data = json.loads(json.dumps(survey_overview_dict))

        # logger.info(str(survey_summary.content.decode()))

        question_mapping = {}

        for question in survey_overview_data['soap:Envelope']['soap:Body']['GetSurveyInformationResponse']['GetSurveyInformationResult']['Survey']['Question']:

            if question['@class'] == "Matrix":

                question_mapping[question['@heading']] = []

                for column in question['Side']['Topic']:
                    question_mapping[question['@heading']].append(column['@column'])

            if question['@class'] == "FillIn":
                question_mapping[question['@heading']] = question['Option']['@column']

        survey_details = requests.post(self.url, data=survey_details_data, headers=surveyJsonHeaders, verify=True)

        survey_details_dict = xmltodict.parse(survey_details.content.decode())
        survey_details_data = json.loads(json.dumps(survey_details_dict))

        allAnswers = []
        answerMetrics = ""

        for answer in survey_details_data['soap:Envelope']['soap:Body']['GetSurveyDataResponse']['GetSurveyDataResult']['diffgr:diffgram']['NewDataSet']['Table1']:

            dateCheck = datetime.strptime(answer['completed'][:-1], '%Y-%m-%dT%H:%M:%S.%f')

            if int(dateCheck.timestamp()) > int(datetime.now().timestamp() - 60):
                allAnswers.append(
                    {"timestamp": int(dateCheck.timestamp()), "content": str(answer), "log.source": "verint","level": "info"})

                for attributes in answer:

                    for questions in question_mapping:

                        if str(type(question_mapping[str(questions)])) == "<class 'list'>":

                            for item in question_mapping[str(questions)]:

                                if attributes == item:
                                    answerMetrics += "verint,project=" + str(self.project_id) + ",question=" + item + " " + \
                                                     answer[str(item)] + "\n"

        metric_headers = {"Authorization": "Api-token " + self.token}
        log_headers = {"Authorization": "Api-token " + self.token, "Content-Type": "application/json; charset=utf-8","Accept": "application/json; charset=utf-8"}

        if answerMetrics != "":

            requests.post(self.dt_url + "api/v2/metrics/ingest", data=answerMetrics, headers=metric_headers,verify=True)

        if allAnswers != []:

            requests.post(self.dt_url + "api/v2/logs/ingest", data=str(json.dumps(allAnswers)), headers=log_headers,verify=True)
