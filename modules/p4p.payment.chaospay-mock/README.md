# p4p.payment.chaospay-mock

Planned internal chaos payment mock for later pilot-node stress tests.

This module is not a real payment provider and is not executable yet. It exists so operator tooling can already show the intended module boundary without claiming production payment behavior.

Planned scenarios:

- instant success
- user cancelled payment
- provider timeout
- duplicate callback or webhook
- late payment callback after order expiry
- wrong amount
- wrong currency
- invalid signature
- provider says paid after the order was cancelled
- merchant confirms without valid payment
- payment status changes out of order
- duplicate callbacks with conflicting information
