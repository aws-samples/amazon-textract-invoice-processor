## Build a receipt and invoice processing pipeline with Amazon Textract
The repository provides a reference architecture to  build a invoice automation pipeline that enables extraction, verification, archival and intelligent search.

### Architecture
The following architecture diagram shows the stages of a receipt and invoice processing workflow. It starts with a Document Capture stage to securely collect and store scanned invoices and receipts. The next stage is the extraction phase where we pass the collected invoices and receipts to Amazon Textract’s AnalyzeExpense API to extract financially related relationships between text such as Vendor Name, Invoice Receipt Date, Order Date, Amount Due/Paid, etc. In the next stage, we use few pre-defined expense rules to determine if we should auto-auto approve or reject our receipt. Auto approved and rejected documents go to their respective S3 buckets. For auto-approved documents, you can search all the extracted fields and values using OpenSearch. The indexed metadata can be visualized using OpenSearch dashboard.. Auto-approved documents are also set up to be moved to Glacier Vault for long term archival using S3 lifecycle policies. 

![Architecture](invoice-processing-architecture.png)

### Steps to deploy

####  Clone the repository
```bash
git clone https://github.com/aws-samples/amazon-textract-invoice-processor.git
```

#### Install dependencies
```bash
pip install -r requirements.txt
```

#### Deploy InvoiceProcessor stack
```bash
cdk deploy
```

The deployment takes around 25 minutes with the default configuration settings from the GitHub samples, and creates a Step Functions workflow, which is invoked when a document is put at an Amazon S3 bucket/prefix and subsequently is processed till the content of the document is indexed in an OpenSearch cluster.

The following is a sample output including useful links and information generated from `cdk deploy` command:

```bash
Outputs:
InvoiceProcessorWorkflow.CognitoUserPoolLink = https://us-east-2.console.aws.amazon.com/cognito/v2/idp/user-pools/us-east-2_f45Cf0MWa/users?region=us-east-2
InvoiceProcessorWorkflow.DocumentQueueLink = https://us-east-2.console.aws.amazon.com/sqs/v2/home?region=us-east-2#/queues/https%3A%2F%2Fsqs.us-east-2.amazonaws.com%2F145020893107%2FInvoiceProcessorWorkflow-ExecutionThrottleDocumentQueueDC0218C-r6P9PQvlZsJ2.fifo
InvoiceProcessorWorkflow.DocumentUploadLocation = s3://invoiceprocessorworkflow-invoiceprocessorbucketf1-lzei1g235krx/uploads/
InvoiceProcessorWorkflow.OpenSearchDashboard = https://search-idp-cdk-opensearch-n3r3zkhwlabgz6vp5lq4bk7yf4.us-east-2.es.amazonaws.com/_dashboards
InvoiceProcessorWorkflow.OpenSearchLink = https://us-east-2.console.aws.amazon.com/aos/home?region=us-east-2#/opensearch/domains/idp-cdk-opensearch
InvoiceProcessorWorkflow.RulesTableName = InvoiceProcessorWorkflow-ExpenseValidationRulesTableEB3DAEF1-I1IY5U27MWF7
InvoiceProcessorWorkflow.StepFunctionFlowLink = https://us-east-2.console.aws.amazon.com/states/home?region=us-east-2#/statemachines/view/arn:aws:states:us-east-2:145020893107:stateMachine:InvoiceProcessorF68A161B-lcypjz3p5YZc
```

This information is also available in the AWS CloudFormation Console.

After the ckd deployment is complete, create a couple of validation rules in Dynamodb table. You can open CloudShell from AWS Console and run these commands:
```bash
aws dynamodb execute-statement --statement "INSERT INTO \"$(aws cloudformation list-exports --query 'Exports[?Name==`InvoiceProcessorWorkflow-RulesTableName`].Value' --output text)\" VALUE {'ruleId': 1, 'type': 'regex', 'field': 'INVOICE_RECEIPT_ID', 'check': '(?i)[0-9]{3}[a-z]{3}[0-9]{3}$', 'errorTxt': 'Receipt number is not valid. It is of the format: 123ABC456'}"
aws dynamodb execute-statement --statement "INSERT INTO \"$(aws cloudformation list-exports --query 'Exports[?Name==`InvoiceProcessorWorkflow-RulesTableName`].Value' --output text)\" VALUE {'ruleId': 2, 'type': 'regex', 'field': 'PO_NUMBER', 'check': '(?i)[a-z0-9]+$', 'errorTxt': 'PO number is not present'}"
```

When a new document is placed under the InvoiceProcessorWorkflow.DocumentUploadLocation, a new Step Functions workflow is started for this document.

To check the status of this document, the InvoiceProcessorWorkflow.StepFunctionFlowLink provides a link to the list of StepFunction executions in the AWS Management Console, displaying the status of the document processing for each document uploaded to Amazon S3. The tutorial Viewing and debugging executions on the Step Functions console provides an overview of the components and views in the AWS Console.


## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

