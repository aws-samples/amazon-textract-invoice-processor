#!/usr/bin/env python3
from cdk.invoice_processor import InvoiceProcessorWorkflow
import aws_cdk as cdk

app = cdk.App()
InvoiceProcessorWorkflow(app, "InvoiceProcessorWorkflow")
app.synth()
