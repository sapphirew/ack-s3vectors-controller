# Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may
# not use this file except in compliance with the License. A copy of the
# License is located at
#
#	 http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.
"""Integration tests for the S3 Vectors Index resource."""

import time

import pytest

from acktest import tags
from acktest.k8s import condition
from acktest.k8s import resource as k8s
from acktest.resources import random_suffix_name

from e2e import (
    CRD_GROUP,
    CRD_VERSION,
    load_s3vectors_resource,
    service_marker,
)
from e2e.replacement_values import REPLACEMENT_VALUES

VECTOR_BUCKET_PLURAL = "vectorbuckets"
INDEX_PLURAL = "indices"

CREATE_WAIT_AFTER_SECONDS = 20
MODIFY_WAIT_AFTER_SECONDS = 20
DELETE_WAIT_AFTER_SECONDS = 20


def get_index(s3vectors_client, vector_bucket_name: str, index_name: str):
    """Returns the index from AWS, or None if it does not exist."""
    try:
        return s3vectors_client.get_index(
            vectorBucketName=vector_bucket_name, indexName=index_name
        )
    except s3vectors_client.exceptions.NotFoundException:
        return None


@service_marker
@pytest.mark.canary
class TestIndex:
    def test_create_update_delete(self, s3vectors_client):
        # Provision the parent VectorBucket first; the Index references it.
        vector_bucket_name = random_suffix_name("ack-test-vb", 32)
        vb_replacements = REPLACEMENT_VALUES.copy()
        vb_replacements["VECTOR_BUCKET_NAME"] = vector_bucket_name
        vb_data = load_s3vectors_resource(
            "vector_bucket", additional_replacements=vb_replacements
        )
        vb_ref = k8s.CustomResourceReference(
            CRD_GROUP, CRD_VERSION, VECTOR_BUCKET_PLURAL,
            vector_bucket_name, namespace="default",
        )
        k8s.create_custom_resource(vb_ref, vb_data)
        k8s.wait_resource_consumed_by_controller(vb_ref)
        time.sleep(CREATE_WAIT_AFTER_SECONDS)
        assert k8s.wait_on_condition(
            vb_ref, condition.CONDITION_TYPE_RESOURCE_SYNCED, "True", wait_periods=10,
        )

        try:
            index_name = random_suffix_name("ack-test-idx", 32)
            replacements = REPLACEMENT_VALUES.copy()
            replacements["INDEX_NAME"] = index_name
            replacements["VECTOR_BUCKET_NAME"] = vector_bucket_name

            index_data = load_s3vectors_resource(
                "index", additional_replacements=replacements
            )
            index_ref = k8s.CustomResourceReference(
                CRD_GROUP, CRD_VERSION, INDEX_PLURAL,
                index_name, namespace="default",
            )
            k8s.create_custom_resource(index_ref, index_data)
            cr = k8s.wait_resource_consumed_by_controller(index_ref)

            assert cr is not None
            assert k8s.get_resource_exists(index_ref)

            time.sleep(CREATE_WAIT_AFTER_SECONDS)

            assert k8s.wait_on_condition(
                index_ref, condition.CONDITION_TYPE_RESOURCE_SYNCED, "True", wait_periods=10,
            )

            cr = k8s.get_resource(index_ref)
            assert "status" in cr
            arn = cr["status"]["ackResourceMetadata"]["arn"]
            assert arn is not None
            assert cr["status"]["ackResourceMetadata"]["ownerAccountID"] is not None
            assert cr["status"].get("creationTime") is not None

            # Verify in AWS. GetIndex wraps the resource in an `index` member.
            aws_index = get_index(s3vectors_client, vector_bucket_name, index_name)
            assert aws_index is not None
            assert aws_index["index"]["indexName"] == index_name
            assert aws_index["index"]["dataType"] == "float32"
            assert aws_index["index"]["dimension"] == 128
            assert aws_index["index"]["distanceMetric"] == "cosine"

            # Tags applied at creation.
            resource_tags = s3vectors_client.list_tags_for_resource(resourceArn=arn)["tags"]
            tags.assert_present({"environment": "test", "team": "ack"}, resource_tags)

            # Update: tags only (all index config fields are immutable).
            tag_updates = {
                "spec": {
                    "tags": {
                        "environment": "prod",
                        "owner": "platform",
                        "team": None,
                    },
                },
            }
            k8s.patch_custom_resource(index_ref, tag_updates)
            time.sleep(MODIFY_WAIT_AFTER_SECONDS)

            assert k8s.wait_on_condition(
                index_ref, condition.CONDITION_TYPE_RESOURCE_SYNCED, "True", wait_periods=10,
            )

            resource_tags = s3vectors_client.list_tags_for_resource(resourceArn=arn)["tags"]
            tags.assert_equal_without_ack_tags(
                {"environment": "prod", "owner": "platform"}, resource_tags
            )

            # Delete the index and confirm it is gone from AWS.
            _, deleted = k8s.delete_custom_resource(index_ref)
            assert deleted
            time.sleep(DELETE_WAIT_AFTER_SECONDS)
            assert get_index(s3vectors_client, vector_bucket_name, index_name) is None
        finally:
            k8s.delete_custom_resource(vb_ref)
            time.sleep(DELETE_WAIT_AFTER_SECONDS)
