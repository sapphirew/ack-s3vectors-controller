	// DeleteVectorBucket rejects requests that set BOTH vectorBucketName and
	// vectorBucketArn. ACK populates both; clear the ARN so the delete keys off
	// the name alone.
	input.VectorBucketArn = nil
