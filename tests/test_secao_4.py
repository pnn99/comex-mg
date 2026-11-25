"""Casos sintéticos para agrupamentos, exposição e regressão da seção 4."""
import unittest

import numpy as np
import pandas as pd

from analise_perfis import ari, kmeans, padronizar, quadrados, qualidade, ward
from analise_resiliencia import classificar_tarifas, desfechos, exposicao, regressao


class SecaoQuatro(unittest.TestCase):
    def test_synthetic_grupos_e_metricas(self):
        x = np.array([[0.], [1.], [10.], [11.]])
        esperado = [1, 1, 0, 0]
        for g in [ward(x, [2])[2], kmeans(x, 2, np.random.default_rng(2026))]:
            self.assertEqual(ari(g, esperado), 1)
            sil, db, menor = qualidade(x, np.sqrt(quadrados(x,x)), g)
            self.assertEqual(menor, 2)
            self.assertAlmostEqual(db, .1)
            self.assertAlmostEqual(sil, 1 - (.5 / 9.5 + .5 / 10.5))
        self.assertAlmostEqual(ari(esperado, [0, 1, 0, 1]), -.5)
        np.testing.assert_allclose(padronizar(x), padronizar(100 * x + 7))

    def test_synthetic_exposicao_parcial_e_sem_eua(self):
        produtos = pd.DataFrame({"CO_MUN":["a","a","b"],"SH4":["0901","2009","0901"],
                                 "eua":[30,10,0],"total":[50,50,10]})
        # Recorte sintético para testar exceção parcial, integral e denominador zero.
        codigos = ["20091100", "20091900", "09011100","09011200","09012100","09012200","09019010","09019020"]
        lista = pd.DataFrame({"HTS8": codigos, "SH4": [c[:4] for c in codigos], "tipo": "subposicao",
                              "ato": ["EO14323"] + ["EO14361"] * 7,
                              "vigencia": ["2025-08-06"] + ["2025-11-13"] * 7})
        pesos = classificar_tarifas(pd.Index(["0901","2009"], name="SH4"), lista)
        t = exposicao(produtos, pesos).set_index(["medida","CO_MUN"])
        for medida in pesos.medida.unique():
            self.assertAlmostEqual(t.loc[(medida,"a"),"exposicao_min"], .3)
            self.assertAlmostEqual(t.loc[(medida,"a"),"exposicao_max"], .4)
            self.assertAlmostEqual(t.loc[(medida,"a"),"cobertura_fob_eua"], .75)
            self.assertTrue(np.isnan(t.loc[(medida,"b"),"cobertura_fob_eua"]))
            self.assertEqual(t.loc[(medida,"b"),"exposicao_max"], 0)

    def test_synthetic_resistencia_denominador_zero(self):
        d = pd.DataFrame({"eua_antes":[0,2,1], "eua_depois":[0,1,1],
                          "outros_antes":[0,0,0], "outros_depois":[0,0,0],
                          "delta_eua":[0,-1,0],"delta_total":[0,-1,0]})
        r = desfechos(d)
        self.assertTrue(np.isnan(r.resistiu_eua_pct.iloc[0]))
        self.assertTrue(np.isnan(r.crescimento_simetrico_total_pct.iloc[0]))
        np.testing.assert_allclose(r.resistiu_eua_pct.iloc[1:], [0,100])

    def test_synthetic_hc3(self):
        t = pd.DataFrame({"x":[0,1,2,3,4], "y":[1,3,2,5,4]})
        r = regressao(t,"y",["x"]).set_index("termo")
        self.assertAlmostEqual(r.loc["x","coef"], .8)
        # Resíduos leave-one-out equivalem a u/(1-h) para HC3.
        omitidos = []
        for i, linha in t.iterrows():
            b, a = np.polyfit(t.drop(i).x,t.drop(i).y,1)
            omitidos.append(linha.y - (a + b * linha.x))
        peso = (t.x - t.x.mean()) / ((t.x - t.x.mean())**2).sum()
        self.assertAlmostEqual(r.loc["x","ep_hc3"], np.linalg.norm(peso * omitidos))


if __name__ == "__main__":
    unittest.main()
