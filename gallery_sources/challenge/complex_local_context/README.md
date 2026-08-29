# complex_local_context

The theorem carries an implicit type, a type-class-provided coercion, a local
term, and a hypothesis whose type depends on that coercion.  `Error.lean`
changes only the final proof term from `h` to `x`, producing a context-sensitive
type mismatch while keeping the full binder structure inside the theorem.

