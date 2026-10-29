class PublishResultUncertainError(RuntimeError):
    """发布结果不确定异常。

    当发布已经尝试提交，但限定时间内无法从平台页面确认结果时抛出。
    此异常会触发任务进入 "uncertain"（结果待核对）状态，提醒运营人员
    必须先到平台后台人工核对，确认前不要重试，避免重复发布。
    """


class PlatformRateLimitedError(RuntimeError):
    """A platform explicitly asked this account to stop submitting requests."""

    status = "rate_limited"

    def __init__(self, platform: str, message: str) -> None:
        super().__init__(message)
        self.platform = platform
