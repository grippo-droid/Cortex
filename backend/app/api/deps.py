"""Shared route dependencies.

`get_current_user` lands here in T1.3. Every user-scoped query must take its
`user_id` from the verified JWT and never from client-supplied input — see
docs/03_Security_and_Access.md section 2.
"""
