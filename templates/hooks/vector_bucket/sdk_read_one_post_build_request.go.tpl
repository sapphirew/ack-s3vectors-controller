	// GetVectorBucket rejects requests that set BOTH vectorBucketName and
	// vectorBucketArn ("Must specify either ... but not both"). ACK populates
	// both (name from Spec, ARN from status metadata), so clear the ARN and key
	// the read off the name alone.
	input.VectorBucketArn = nil
