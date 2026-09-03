# mk/

Drop-in make fragments. A Phase-2 gate registers itself with one line:

```make
VALIDATE_GATES += validate-catalog
```

in `mk/catalog.mk`. The Makefile `-include`s every `mk/*.mk`, so the aggregate
`make validate-rupture` picks it up without anyone editing the Makefile.
