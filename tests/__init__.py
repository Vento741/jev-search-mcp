import os

# The developer machine has a real key and may have provider settings: no test may
# ever reach a paid provider or depend on local JEV_SEARCH_* configuration.
for _name in [k for k in os.environ if k.startswith("JEV_SEARCH_")]:
    del os.environ[_name]
