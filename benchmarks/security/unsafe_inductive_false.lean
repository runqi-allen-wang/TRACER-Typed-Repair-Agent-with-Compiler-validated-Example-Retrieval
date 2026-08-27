unsafe inductive Bad
  | mk : (Bad → False) → Bad

unsafe example : False :=
  have notBad (b : Bad) : False := match b with
    | .mk f => f (.mk f)
  have bad : Bad := .mk notBad
  notBad bad
