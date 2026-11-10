"""Forward-only splits using half-open event and validation intervals."""


def purged_folds(samples, windows, horizon, embargo=86400):
    if horizon <= 0 or embargo < 0:
        raise ValueError("Invalid horizon or embargo")
    embargoes = []
    previous_end = None
    for first, last in windows:
        if last <= first or (previous_end is not None and first < previous_end):
            raise ValueError("Validation windows must be ordered and disjoint")
        train, valid = [], []
        for i, sample in enumerate(samples):
            start, end = sample.start, sample.end
            if end <= start or end > start+horizon:
                raise ValueError("Invalid outcome interval")
            if end <= first-embargo and not any(start < b and end > a for a,b in embargoes):
                train.append(i)
            if first <= start and start+horizon <= last:
                valid.append(i)
        yield train, valid
        embargoes.append((last,last+embargo))
        previous_end = last
