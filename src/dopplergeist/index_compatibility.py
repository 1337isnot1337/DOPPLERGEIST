"""Source-pinned equivalent prepared-index normalization implementations."""

# The cache-size-only change and this exact compatibility check do not change
# decoded observations or normalization. Any source edit disables this mapping.
PREPARED_DATA_ACCESS_EQUIVALENCE = {
    # The native collector only replaces canonical Python column extraction.
    "ddd77e9734fff6a70cc9195bd1305002f9f78e39ea601f27e0f596dcb336033a": (
        "275e38a37f82993b609b6b78c113d35c4da269083ceb3afcb1d94ada48bdc0d4",
        "dad02d09d89ad9d267cd8d0424b8e018d0399a28d6b43903b5a55867290b3957",
        "d664caf4b496599d29a81360c4a9d9736a3248c157e71d885463b349aad6dd36",
    ),
    "275e38a37f82993b609b6b78c113d35c4da269083ceb3afcb1d94ada48bdc0d4": (
        "dad02d09d89ad9d267cd8d0424b8e018d0399a28d6b43903b5a55867290b3957",
        "d664caf4b496599d29a81360c4a9d9736a3248c157e71d885463b349aad6dd36",
    ),
}
