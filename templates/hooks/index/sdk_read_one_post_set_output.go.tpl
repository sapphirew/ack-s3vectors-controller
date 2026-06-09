	// GetIndex does not return resource tags. Fetch them via ListTagsForResource
	// so the delta against Spec.Tags is accurate and we avoid spurious deltas
	// (and the resulting reconcile loop).
	if err := rm.setResourceTags(ctx, ko); err != nil {
		return nil, err
	}
