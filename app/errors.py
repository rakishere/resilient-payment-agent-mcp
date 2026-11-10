"""Application errors distinguish outages from security/business failures."""

class PaymentError(Exception):
    code = "PAYMENT_ERROR"
    http_status = 400

class InvalidPaymentId(PaymentError):
    code = "INVALID_PAYMENT_ID"

class NotAuthorized(PaymentError):
    code = "NOT_AUTHORIZED"
    http_status = 403

class PaymentNotFound(PaymentError):
    code = "PAYMENT_NOT_FOUND"
    http_status = 404

class ProviderUnavailable(PaymentError):
    code = "STRIPE_UNAVAILABLE"
    http_status = 503

class McpUnavailable(PaymentError):
    code = "MCP_UNAVAILABLE"
    http_status = 503

class ConfigurationError(PaymentError):
    code = "CONFIGURATION_ERROR"
    http_status = 500
