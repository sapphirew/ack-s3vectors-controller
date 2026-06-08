// Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License"). You may
// not use this file except in compliance with the License. A copy of the
// License is located at
//
//     http://aws.amazon.com/apache2.0/
//
// or in the "license" file accompanying this file. This file is distributed
// on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
// express or implied. See the License for the specific language governing
// permissions and limitations under the License.

package vector_bucket

import (
	"context"

	ackcompare "github.com/aws-controllers-k8s/runtime/pkg/compare"
	ackrtlog "github.com/aws-controllers-k8s/runtime/pkg/runtime/log"
	svcapitypes "github.com/aws-controllers-k8s/s3vectors-controller/apis/v1alpha1"
	"github.com/aws/aws-sdk-go-v2/aws"
	svcsdk "github.com/aws/aws-sdk-go-v2/service/s3vectors"
)

// arnFromKO returns the resource ARN string pointer from the resource's status
// metadata, or nil if it has not yet been populated.
func arnFromKO(ko *svcapitypes.VectorBucket) *string {
	if ko.Status.ACKResourceMetadata == nil || ko.Status.ACKResourceMetadata.ARN == nil {
		return nil
	}
	return (*string)(ko.Status.ACKResourceMetadata.ARN)
}

// setResourceTags populates the VectorBucket spec tags from the dedicated
// ListTagsForResource API, since GetVectorBucket does not return them.
func (rm *resourceManager) setResourceTags(
	ctx context.Context,
	ko *svcapitypes.VectorBucket,
) (err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.setResourceTags")
	defer func() { exit(err) }()

	arn := arnFromKO(ko)
	if arn == nil {
		return nil
	}

	tagsResp, err := rm.sdkapi.ListTagsForResource(
		ctx,
		&svcsdk.ListTagsForResourceInput{ResourceArn: arn},
	)
	rm.metrics.RecordAPICall("READ_ONE", "ListTagsForResource", err)
	if err != nil {
		return err
	}
	if len(tagsResp.Tags) > 0 {
		ko.Spec.Tags = aws.StringMap(tagsResp.Tags)
	} else {
		ko.Spec.Tags = nil
	}

	return nil
}

// customUpdateVectorBucket reconciles the only mutable surface of a
// VectorBucket: its tags. There is no UpdateVectorBucket API; the bucket name
// and encryption configuration are immutable (encryption is set at create and
// has no Put/Update API).
func (rm *resourceManager) customUpdateVectorBucket(
	ctx context.Context,
	desired *resource,
	latest *resource,
	delta *ackcompare.Delta,
) (updated *resource, err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.customUpdateVectorBucket")
	defer func() { exit(err) }()

	ko := desired.ko.DeepCopy()
	ko.Status = *latest.ko.Status.DeepCopy()

	arn := arnFromKO(ko)
	if arn == nil {
		return &resource{ko}, nil
	}

	if delta.DifferentAt("Spec.Tags") {
		if err := rm.syncTags(ctx, desired, latest, arn); err != nil {
			return nil, err
		}
	}

	return &resource{ko}, nil
}

// syncTags reconciles the desired tag set against the latest observed tag set
// using the TagResource and UntagResource APIs.
func (rm *resourceManager) syncTags(
	ctx context.Context,
	desired *resource,
	latest *resource,
	arn *string,
) (err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.syncTags")
	defer func() { exit(err) }()

	from, _ := convertToOrderedACKTags(latest.ko.Spec.Tags)
	to, _ := convertToOrderedACKTags(desired.ko.Spec.Tags)

	added, _, removed := ackcompare.GetTagsDifference(from, to)

	// A key present in both added and removed is a value change; keep it in
	// added (TagResource overwrites) and drop it from removed.
	for key := range removed {
		if _, ok := added[key]; ok {
			delete(removed, key)
		}
	}

	if len(removed) > 0 {
		toRemove := make([]string, 0, len(removed))
		for key := range removed {
			toRemove = append(toRemove, key)
		}
		_, err = rm.sdkapi.UntagResource(
			ctx,
			&svcsdk.UntagResourceInput{
				ResourceArn: arn,
				TagKeys:     toRemove,
			},
		)
		rm.metrics.RecordAPICall("UPDATE", "UntagResource", err)
		if err != nil {
			return err
		}
	}

	if len(added) > 0 {
		toAdd := make(map[string]string, len(added))
		for key, val := range added {
			toAdd[key] = val
		}
		_, err = rm.sdkapi.TagResource(
			ctx,
			&svcsdk.TagResourceInput{
				ResourceArn: arn,
				Tags:        toAdd,
			},
		)
		rm.metrics.RecordAPICall("UPDATE", "TagResource", err)
		if err != nil {
			return err
		}
	}

	return nil
}
