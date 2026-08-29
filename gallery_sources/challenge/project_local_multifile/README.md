# project_local_multifile

This minimal Lake project imports `Challenge.Helper` from another project-local
file.  `Error.lean` changes only the expected result from `2` to `3`.  The case
checks both theorem extraction and whether the generated capsule retains enough
of the local module build environment to replay the original equality failure.

