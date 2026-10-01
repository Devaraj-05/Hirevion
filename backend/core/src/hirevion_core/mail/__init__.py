"""Transactional email: templates, and delivery through the outbox (SP-02 spec, "Email").

A change writes its email to the outbox in its own transaction (`queue_mail`); the relay
publishes it to the `mail` stream, and `MailConsumer` renders, sends and acknowledges it.
"""
