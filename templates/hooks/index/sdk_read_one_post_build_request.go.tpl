	// GetIndex rejects requests that set the name pair AND indexArn together.
	// ACK populates indexArn from status metadata; clear it so the read keys
	// off vectorBucketName + indexName.
	input.IndexArn = nil
