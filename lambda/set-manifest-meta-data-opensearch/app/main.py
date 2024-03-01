import json
import logging
import os
import re
import uuid
# import debugpy
import textractmanifest as tm
import datetime
from typing import Tuple
import trp.trp2_expense as t2
import boto3
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# debugpy.listen(5678)
# debugpy.wait_for_client()

# if table rules are updated more frequently, change this implementation
# to a caching one so it gets updated even when the Lambda stays active
table = dynamodb.Table(os.environ.get("RULES_TABLE", "expenseValidationRules"))
response = table.scan()
rules = response["Items"]

def split_s3_path_to_bucket_and_key(s3_path: str) -> Tuple[str, str]:
    if len(s3_path) > 7 and s3_path.lower().startswith("s3://"):
        s3_bucket, s3_key = s3_path.replace("s3://", "").split("/", 1)
        return (s3_bucket, s3_key)
    else:
        raise ValueError(
            f"s3_path: {s3_path} is no s3_path in the form of s3://bucket/key."
        )


def get_file_from_s3(s3_path: str, range=None) -> bytes:
    s3_bucket, s3_key = split_s3_path_to_bucket_and_key(s3_path)
    if range:
        o = s3.get_object(Bucket=s3_bucket, Key=s3_key, Range=range)
    else:
        o = s3.get_object(Bucket=s3_bucket, Key=s3_key)
    return o.get("Body").read()


def create_meta_data_dict(manifest: tm.IDPManifest) -> dict:
    meta_data_dict: dict = dict()
    if manifest.meta_data:
        for meta_data in manifest.meta_data:
            logger.debug(f"meta_data: {meta_data}")
            meta_data_dict[meta_data.key] = meta_data.value
    return meta_data_dict


def create_bulk_import_line(index, action, doc_id, doc):
    action_line = {action: {"_index": index, "_id": doc_id}}
    return json.dumps(action_line) + "\n" + json.dumps(doc) + "\n"


def lambda_handler(event, _):
    """the s3path in the manifest has to be in the format <start_page>-<end_page>.suffix"""
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    logger.setLevel(log_level)
    logger.info(f"LOG_LEVEL: {log_level}")
    logger.info(json.dumps(event))
    csv_s3_output_prefix = os.environ.get("S3_OPENSEARCH_OUTPUT_PREFIX")
    csv_s3_output_bucket = os.environ.get("S3_OPENSEARCH_OUTPUT_BUCKET")
    if not csv_s3_output_prefix or not csv_s3_output_bucket:
        raise ValueError(
            "require S3_OPENSEARCH_OUTPUT_BUCKET and S3_OPENSEARCH_OUTPUT_PREFIX"
        )
    opensearch_index = os.environ.get("OPENSEARCH_INDEX", "my-index")

    if "Payload" in event and "manifest" in event["Payload"]:
        manifest: tm.IDPManifest = tm.IDPManifestSchema().load(
            event["Payload"]["manifest"]
        )  # type: ignore
    elif "manifest" in event:
        manifest: tm.IDPManifest = tm.IDPManifestSchema().load(
            event["manifest"]
        )  # type: ignore
    else:
        manifest: tm.IDPManifest = tm.IDPManifestSchema().load(event)  # type: ignore
    s3_path = manifest.s3_path
    origin_file_uri = event["originFileURI"]
    result_value = ""
    # The expected file pattern is "<start_page_number>-<end_page_number>.suffix"
    pages, _ = os.path.splitext(os.path.basename(s3_path))
    start_page, _ = pages.split("-")
    start_page_number = int(start_page)

    origin_file_name, _ = os.path.splitext(os.path.basename(urlparse(origin_file_uri).path))

    analyzed_expense_json = json.loads(
        get_file_from_s3(
            s3_path=event["textract_result"]["TextractOutputJsonPath"]
        ).decode("utf-8")
    )

    exp_docs: t2.TAnalyzeExpenseDocument = t2.TAnalyzeExpenseDocumentSchema().load(
        analyzed_expense_json
    )  # type: ignore

    base_filename = os.path.basename(s3_path)
    base_filename_no_suffix, _ = os.path.splitext(base_filename)

    s3_output_key = (
        f"{csv_s3_output_prefix}/{str(uuid.uuid4())}/{base_filename_no_suffix}.json"
    )

    for idx, page in enumerate(exp_docs.expenses_documents):
        page_number = start_page_number + idx
        line_texts = " ".join(
            [
                block.text
                for block in page.blocks
                if block.block_type == "LINE" and block.text
            ]
        )

        doc_id = f"{origin_file_name}_{page_number}"
        doc = {
            "content": line_texts,
            "page": page_number,
            "uri": origin_file_uri,
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "origin_file_name": origin_file_name,
        }

        allowed_keys = [
            "TAX_PAYER_ID",
            "VENDOR_VAT_NUMBER",
            "PO_NUMBER",
            "SUBTOTAL",
            "TAX",
            "TOTAL",
            "INVOICE_RECEIPT_ID",
            "ORDER_DATE",
            "DUE_DATE",
            "DELIVERY_DATE",
        ]
        invoice_data = {
            k["Type"]["Text"]: k["ValueDetection"]["Text"]
            for k in analyzed_expense_json["ExpenseDocuments"][0]["SummaryFields"]
            if k["Type"]["Text"] in allowed_keys
        }
        receiver_data_keys = ["CITY", "STATE", "COUNTRY", "STREET"]
        receiver_data_group_key = "RECEIVER_SHIP_TO"
        receiver_data = {
            "{}_{}".format(receiver_data_group_key, k["Type"]["Text"]): k[
                "ValueDetection"
            ]["Text"]
            for k in analyzed_expense_json["ExpenseDocuments"][0]["SummaryFields"]
            if (
                k["Type"]["Text"] in receiver_data_keys
                and (receiver_data_group_key in k["GroupProperties"][0]["Types"])
            )
        }
        invoice_data = {**invoice_data, **receiver_data}

        invoice_data["line_item_count"] = len(
            analyzed_expense_json["ExpenseDocuments"][0]["LineItemGroups"][0][
                "LineItems"
            ]
        )
        filtered_results = {}
        filtered_results["s3_object"] = s3_path
        filtered_results["invoice_data"] = invoice_data
        doc.update(filtered_results)

        # Check Rules
        failing_rules = []
        doc["VERIFICATION_STATUS"] = True
        doc["FAILING_RULES"] = failing_rules
        for rule in rules:
            if rule["field"] in doc['invoice_data']:
                val = doc['invoice_data'][rule["field"]]
                if rule["type"] == "regex":
                    p = re.compile(rule["check"])
                    if p.match(val) is None:
                        failing_rules.append(
                            "[{}] {}".format(rule["ruleId"], rule["errorTxt"])
                        )
            else:
                failing_rules.append(
                    "{} is missing in the input document. It is required for processing".format(
                        rule["field"]
                    )
                )
            if len(failing_rules) > 0:
                doc["VERIFICATION_STATUS"] = False
                doc["FAILING_RULES"] = failing_rules
            print(f"doc: {doc}")
        
        
        copy_source = origin_file_uri.replace("s3://", "")
        if doc["VERIFICATION_STATUS"]:
            s3.copy_object(CopySource=copy_source, Bucket=copy_source.split("/")[0], Key='approved/{}'.format(copy_source.split("/")[-1]))
        else:
            s3.copy_object(CopySource=copy_source, Bucket=copy_source.split("/")[0], Key='declined/{}'.format(copy_source.split("/")[-1]))
        result_value += create_bulk_import_line(
            index=opensearch_index, action="index", doc_id=doc_id, doc=doc
        )
    s3.put_object(
        Body=bytes(result_value.encode("UTF-8")),
        Bucket=csv_s3_output_bucket,
        Key=s3_output_key,
    )

    return {"OpenSearchBulkImport": f"s3://{csv_s3_output_bucket}/{s3_output_key}"}
