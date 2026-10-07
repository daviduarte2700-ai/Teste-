import logging

from .analista import Analista

logging.basicConfig(level=logging.INFO)
print(Analista.do_ambiente().rodar())
