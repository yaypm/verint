import json
import xmltodict
import requests
from datetime import datetime
from ruxit.api.base_plugin import RemoteBasePlugin
import logging
import os
from textblob import TextBlob

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

        # Defining the methods for accessing the file containing the timestamp of the last survey we analysed.
        def read_history(history_path, filename):
            infile = os.path.join(history_path, filename)
            with open(infile) as fin:
                return json.load(fin)

        def write_history(history_path, filename, data):
            outfile = os.path.join(history_path, filename)
            with open(outfile, 'w') as fout:
                json.dump(data, fout)

        def check_history(history_path, filename):
            history_file = os.path.join(history_path, filename)
            exists = os.path.exists(history_file)
            # bool return: True | False
            return exists

        # The file with the historical timestamp exists in a folder called history in the extension directory.
        history_path = os.path.join(os.path.dirname(__file__), 'history/')
        history_filename = "last_timestamp.txt"

        jsonHeaders = {'Content-Type': 'text/xml'}

        # Payloads to set in the requests for logging in, accessing the survey data and getting the actual survey results.
        login_data = "<?xml version=\"1.0\" encoding=\"utf-8\"?><soap:Envelope xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body><Login xmlns=\"http://www.perseus.com/Pdc.WS\"><userName>" + self.username + "</userName><password>" + self.password + "</password></Login></soap:Body></soap:Envelope>"
        survey_summary_data = "<?xml version=\"1.0\" encoding=\"utf-8\"?><soap:Envelope xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body><GetSurveyInformation xmlns=\"http://www.perseus.com/Pdc.WS\"><projectId>" + self.project_id + "</projectId></GetSurveyInformation></soap:Body></soap:Envelope>"
        survey_details_data = "<?xml version=\"1.0\" encoding=\"utf-8\"?><soap:Envelope xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\" xmlns:soap=\"http://schemas.xmlsoap.org/soap/envelope/\"><soap:Body><GetSurveyData xmlns=\"http://www.perseus.com/Pdc.WS\"><projectId>" + self.project_id + "</projectId></GetSurveyData></soap:Body></soap:Envelope>"

        # Post credentials to Verint to login.
        login = requests.post(self.url, data=login_data, headers=jsonHeaders, verify=True)

        logger.info("Login status code: " + str(login.status_code))

        # Set the headers for further requests which will need the cookie values from the login.
        surveyJsonHeaders = {'Content-Type': 'text/xml', 'Host': 'efmpreview.verintefm.com', 'Cookie': ''}
        cookieHeader = ''

        # Extract the 3 cookie values from the login request and put them into the headers.
        for cookie in login.cookies:
            cookieHeader += cookie.name + "=" + cookie.value + ";"

        surveyJsonHeaders['Cookie'] = cookieHeader

        # Get the summary details of the survey including the different questions and sections.
        survey_summary = requests.post(self.url, data=survey_summary_data, headers=surveyJsonHeaders, verify=True)

        logger.info("Survey summary status code: " + str(survey_summary.status_code))

        # Parse the XML response into JSON.
        survey_overview_dict = xmltodict.parse(survey_summary.content.decode())
        survey_overview_data = json.loads(json.dumps(survey_overview_dict))

        question_mapping = {}

        # Loop through the questions from the survey summary and build a list of the questions if they are a
        # Matrix (rating) or FillIn (comment) type
        for question in survey_overview_data['soap:Envelope']['soap:Body']['GetSurveyInformationResponse']['GetSurveyInformationResult']['Survey']['Question']:

            if question['@class'] == "Matrix":

                question_mapping[question['@heading']] = []

                for column in question['Side']['Topic']:
                    question_mapping[question['@heading']].append(column['@column'])

            if question['@class'] == "FillIn":
                question_mapping[question['@heading']] = question['Option']['@column']

        # Get the results of every single survey.
        survey_details = requests.post(self.url, data=survey_details_data, headers=surveyJsonHeaders, verify=True)

        # Convert the XML response to JSON.
        survey_details_dict = xmltodict.parse(survey_details.content.decode())
        survey_details_data = json.loads(json.dumps(survey_details_dict))

        # Define the payload for sending metrics as well as the logs.
        allAnswers = []
        answerMetrics = ""

        # Define last timestamp in case it's not there (first run).
        last_timestamp = 0

        # Define the responses in the JSON payload.
        responses = survey_details_data['soap:Envelope']['soap:Body']['GetSurveyDataResponse']['GetSurveyDataResult']['diffgr:diffgram']['NewDataSet']['Table1']

        #logger.info(str(responses))

        # If there's a previous timestamp, use that.
        if int(read_history(history_path, history_filename)) > 0:

            last_timestamp = read_history(history_path, history_filename)

        # Define the variable to be used to eventually get the latest timestamp.
        temp_timestamp = 0

        # 123
        logger.info("Last timestamp is: " + str(last_timestamp))
        logger.info("Total responses: " + str(len(responses)))
        newResponses = 0

        # Loop through each survey response.
        for answer in responses:

            # Set the survey datetime to the "completed" date of the survey.
            dateCheck = datetime.strptime(answer['completed'][:-1], '%Y-%m-%dT%H:%M:%S.%f')
            dateCheckInt = int(dateCheck.timestamp())

            # Only do something if the response is after the latest one we processed.
            if dateCheckInt > last_timestamp:

                # 123
                # temp_timestamp = dateCheckInt
                if dateCheckInt > temp_timestamp:

                    temp_timestamp = dateCheckInt

                # 123
                newResponses = newResponses + 1

                # Set variables for adding content to answers.
                contentAppend = ""

                # Loop through the different keys/attributes in a survey.
                for attributes in answer:

                    # If it starts with a Q it means it's a question, so put that into the content.
                    if str(attributes).startswith("Q"):

                        contentAppend += str(attributes) + "=" + str(answer[str(attributes)]) + ","

                    # Loop through the questions we gathered from the summary, if we hit a list/rating, use it.
                    for questions in question_mapping:

                        if str(type(question_mapping[str(questions)])) == "<class 'list'>":

                            for item in question_mapping[str(questions)]:

                                if attributes == item:
                                    answerMetrics += "verint,project=" + str(self.project_id) + ",question=" + item + " " + \
                                                     answer[str(item)] + " " + str(dateCheckInt * 1000) + "\n"

                        # Block to add in the NLP processing for sentiment.
                        if str(questions) == "Comments":

                            # We expect one single "comment" in this demo
                            item = question_mapping[str(questions)]

                            if attributes == item:
                                sentence = answer[str(item)]
                                sentiment_metric = TextBlob(sentence).sentiment.polarity

                                answerMetrics += "verint,project=" + str(self.project_id) + ",question=" + item + "_sentiment " + str("%.2f" % round((sentiment_metric + 1) / 2, 2)) + " " + str(dateCheckInt * 1000) + "\n"
                                contentAppend += "sentiment=" + str(round((sentiment_metric + 1) / 2, 2))

                                key_comment = str(item + "_sentiment")
                                val_comment = str("%.2f" % round((sentiment_metric + 1) / 2, 2))

                if key_comment != "":

                    answer[key_comment] = val_comment

                allAnswers.append({"timestamp": int(dateCheck.timestamp()), "content": str(contentAppend),"verint.recordid": str(answer["recordid"]),"verint.campaignid": str(answer["campaignid"]),"verint.campaign_status": str(answer["campaign_status"]), "log.source": "verint","level": "info"})

        # Write the latest timestamp to the file.
        if temp_timestamp != 0:
            
            write_history(history_path, history_filename, temp_timestamp)

        #logger.info(answerMetrics)
        #logger.info(str(json.dumps(allAnswers)))

        # 123
        logger.info("New responses since timestamp: " + str(newResponses))

        metric_headers = {"Authorization": "Api-token " + self.token}
        log_headers = {"Authorization": "Api-token " + self.token, "Content-Type": "application/json; charset=utf-8","Accept": "application/json; charset=utf-8"}

        if answerMetrics != "":

            send_metrics=requests.post(self.dt_url + "api/v2/metrics/ingest", data=answerMetrics, headers=metric_headers,verify=True)
            logger.info("Send metrics is " + str(send_metrics.status_code) + " - " + str(send_metrics.content))

        if allAnswers != []:

            send_logs=requests.post(self.dt_url + "api/v2/logs/ingest", data=str(json.dumps(allAnswers)), headers=log_headers,verify=True)
            logger.info("Send logs is " + str(send_logs.status_code) + " - " + str(send_logs.content))
