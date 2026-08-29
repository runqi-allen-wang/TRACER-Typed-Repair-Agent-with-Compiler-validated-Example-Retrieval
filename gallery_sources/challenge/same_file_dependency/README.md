# same_file_dependency

The target theorem depends on `normalizeNat`, which is declared earlier in the
same file.  `Error.lean` changes only the expected numeral from `2` to `3`, so
the original failure should be the failed equality proof.  The case checks
whether theorem extraction drops the required preceding definition and, if it
does, whether the resulting secondary unknown-name error forces a truthful
full-file fallback.

