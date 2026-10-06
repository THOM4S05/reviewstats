"""Domain failures shared by the mock review page and submission endpoint."""


class ReviewLinkError(Exception):
    pass


class ReviewLinkNotFound(ReviewLinkError):
    pass


class ReviewLinkExpired(ReviewLinkError):
    pass


class ScanpointUnassigned(ReviewLinkError):
    pass
