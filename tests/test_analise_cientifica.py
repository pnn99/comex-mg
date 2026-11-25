"""Casos sintéticos para os indicadores pré-choque."""
import unittest

import numpy as np
import pandas as pd

from analise_cientifica import MESES, calcular_indicadores, comparar_criterios


class IndicadoresMunicipais(unittest.TestCase):
    def setUp(self):
        linhas = []
        for mes in MESES:
            for produto, pais in [("0901", "249"), ("2601", "063")]:
                linhas.append((mes.year, mes.month, "MG", "3100000", produto, pais, 100))
        linhas.extend([
            (2022, 1, "MG", "3100001", "0901", "063", 80),
            (2022, 1, "MG", "3100001", "2601", "063", 20),
            (2022, 2, "MG", "3100001", "2601", "063", 0),
            (2023, 1, "MG", "3100002", "0901", "249", 0),
        ])
        self.dados = pd.DataFrame(linhas, columns=["CO_ANO", "CO_MES", "SG_UF_MUN",
                                                   "CO_MUN", "SH4", "CO_PAIS", "VL_FOB"])

    def test_concentracao_diversidade_exposicao_e_cv(self):
        t = calcular_indicadores(self.dados)
        regular, ocasional = t.loc["3100000"], t.loc["3100001"]
        self.assertEqual(len(t), 2)
        self.assertEqual(regular.hhi_produtos, .5)
        self.assertEqual(regular.numero_efetivo_destinos, 2)
        self.assertEqual(regular.participacao_eua, .5)
        self.assertEqual(regular.cv_mensal, 0)
        self.assertAlmostEqual(ocasional.hhi_produtos, .68)
        self.assertEqual(ocasional.maior_participacao_produtos, .8)
        self.assertEqual(ocasional.hhi_destinos, 1)
        self.assertEqual(ocasional.participacao_eua, 0)
        self.assertEqual((ocasional.meses_ativos, ocasional.meses_com_registro), (1, 2))
        self.assertAlmostEqual(ocasional.cv_mensal, np.sqrt(35))
        c = comparar_criterios(t).set_index("criterio")
        self.assertEqual(c.loc["minimo_12_meses", "municipios"], 1)
        self.assertAlmostEqual(c.loc["minimo_12_meses", "fracao_fob"], 7200 / 7300)

    def test_perda_de_cobertura_e_vazamento(self):
        com_pos = pd.concat([self.dados, self.dados.assign(CO_ANO=2025, VL_FOB=10**9)])
        pd.testing.assert_frame_equal(calcular_indicadores(self.dados), calcular_indicadores(com_pos))
        with self.assertRaisesRegex(ValueError, "36 meses"):
            calcular_indicadores(self.dados[self.dados.CO_MES != 2])
        with self.assertRaisesRegex(ValueError, "duplicada"):
            calcular_indicadores(pd.concat([self.dados, self.dados.iloc[:1]]))
