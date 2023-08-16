import boto3, datetime, json, sys, time

textract_client = boto3.client('textract')

def parse_receipt(event, context):
    print('request received: {}'.format(event))

    analyzed_expense_json = textract_client.analyze_expense(Document={'S3Object': {'Bucket': event['detail']['bucket']['name'], 'Name': event['detail']['object']['key']}})
    allowed_keys = ['TAX_PAYER_ID', 'VENDOR_VAT_NUMBER', 'PO_NUMBER', 'SUBTOTAL', 'TAX', 'TOTAL', 'INVOICE_RECEIPT_ID', 'ORDER_DATE', 'DUE_DATE', 'DELIVERY_DATE']
    invoice_data = {k['Type']['Text']:k['ValueDetection']['Text'] for k in analyzed_expense_json['ExpenseDocuments'][0]['SummaryFields'] if k['Type']['Text'] in allowed_keys}
    receiver_data_keys = ['CITY', 'STATE', 'COUNTRY', 'STREET']
    receiver_data_group_key = 'RECEIVER_SHIP_TO'
    receiver_data = {'{}_{}'.format(receiver_data_group_key, k['Type']['Text']):k['ValueDetection']['Text'] for k in analyzed_expense_json['ExpenseDocuments'][0]['SummaryFields'] if (k['Type']['Text'] in receiver_data_keys and (receiver_data_group_key in k['GroupProperties'][0]['Types']))}
    invoice_data={**invoice_data, **receiver_data}

    invoice_data['line_item_count'] = len(analyzed_expense_json['ExpenseDocuments'][0]['LineItemGroups'][0]['LineItems'])
    invoice_data['upload_date']=str(datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))
    filtered_results={}
    filtered_results['bucket'] = event['detail']['bucket']['name']
    filtered_results['key'] = event['detail']['object']['key']
    filtered_results['invoice_data']=invoice_data

    return filtered_results
