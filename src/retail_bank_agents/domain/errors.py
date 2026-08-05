class BankAgentError(Exception):
    """Base domain exception."""


class ProviderUnavailable(BankAgentError):
    pass


class UnauthorizedAccount(BankAgentError):
    pass


class PaymentNotApprovable(BankAgentError):
    pass


class PaymentExpired(PaymentNotApprovable):
    pass
