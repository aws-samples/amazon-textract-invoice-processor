import boto3, opensearchpy, json, os, re, requests
from opensearchpy import OpenSearch

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('expenseValidationRules')
secretsmanager = boto3.client('secretsmanager')
opensearch_creds = secretsmanager.get_secret_value(SecretId=os.environ['SECRET_ARN'])
response = table.scan()
rules=response['Items']
s3_client=boto3.client('s3')
index_name='invoices'

opensearch_client = OpenSearch(
    hosts = [{'host': os.environ['OPENSEARCH_DOMAIN'], 'port': 443}],
    http_auth = (json.loads(opensearch_creds['SecretString'])['username'], json.loads(opensearch_creds['SecretString'])['password']),
    use_ssl = True,
    http_compress = True
)

def push_event_to_opensearch(doc):
    if opensearch_client.indices.exists(index_name):
        print('index exists')
        opensearch_client.index(
            index = index_name,
            body = doc,
            refresh = True
        )
    else:
        index_body  = {
            'settings': {
                'index': {
                'number_of_shards': 4
                }
            }
        }
        opensearch_client.indices.create(index_name, body=index_body)
        opensearch_client.index(
            index = index_name,
            body = doc,
            refresh = True
        )


def validate_input(inputdict):
    failing_rules=[]
    doc=inputdict['invoice_data']
    for rule in rules:
        if rule['field'] in doc:
            val=doc[rule['field']]
            if rule['type'] == 'regex':
                p = re.compile(rule['check'])
                if p.match(val) is None:
                    failing_rules.append('[{}] {}'.format(rule['ruleId'], rule['errorTxt']))
        else:
            failing_rules.append('{} is missing in the input document. It is required for processing'.format(rule['field']))
    
    if len(failing_rules) == 0:
        doc['VERIFICATION_STATUS']=True
        doc['DOC_LOCATION']='{}/{}'.format(os.environ['APPROVED_BUCKET_NAME'], inputdict['key'])
        push_event_to_opensearch(doc)
        print('Invoice is valid. Moving to approved bucket: {}/{}'.format(os.environ['APPROVED_BUCKET_NAME'], inputdict['key']))
        s3_client.copy_object(Bucket=os.environ['APPROVED_BUCKET_NAME'], Key=inputdict['key'], CopySource={'Bucket': inputdict['bucket'], 'Key': inputdict['key']})
    else:
        doc['VERIFICATION_STATUS']=False
        doc['DOC_LOCATION']='{}/{}'.format(os.environ['DENIED_BUCKET_NAME'], inputdict['key'])
        push_event_to_opensearch(doc)
        print('Invoice is invalid. Moving to denied bucket: {}/{}'.format(os.environ['DENIED_BUCKET_NAME'], inputdict['key']))
        s3_client.copy_object(Bucket=os.environ['DENIED_BUCKET_NAME'], Key=inputdict['key'], CopySource={'Bucket': inputdict['bucket'], 'Key': inputdict['key']})
  

def expense_verifier(event, context):
    print('request received: {}'.format(event))
    validate_input(event)
    return event
