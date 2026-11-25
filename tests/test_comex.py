"""Testes com respostas sintéticas da API municipal."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import requests

import analise_comex as comex


class ConsultasMunicipais(unittest.TestCase):
    def test_linha_posicional_sem_cabecalho_informa_origem(self):
        with self.assertRaisesRegex(ValueError, "GET /cities/filters/country"):
            list(comex.registros_api([["063", "Exemplo"]], "GET /cities/filters/country", {"id", "text"}))

    def test_limite_usa_competencia_e_respeita_virada_do_ano(self):
        with patch.object(comex, "date", wraps=date) as calendario:
            calendario.today.return_value = date(2027, 1, 10)
            for mes, esperado in [("11", 11), ("12", 12)]:
                publicado = {"year": "2026", "monthNumber": mes, "updated": "2027-01-08"}
                with patch.object(comex, "consultar_api", return_value=publicado):
                    self.assertEqual(comex.limite_publicado().month, esperado)
            with patch.object(comex, "consultar_api", return_value={"year": "2027", "monthNumber": "1"}):
                self.assertEqual(comex.limite_publicado(), date(2026, 12, 31))
            with patch.object(comex, "consultar_api", side_effect=requests.ConnectionError("offline")):
                self.assertEqual(comex.limite_publicado(), date(2026, 12, 31))

    def setUp(self):
        comex.catalogo_api.cache_clear()
        comex.filtro_mg.cache_clear()
        self.addCleanup(comex.catalogo_api.cache_clear)
        self.addCleanup(comex.filtro_mg.cache_clear)

    def resposta(self, metodo, url, **opcoes):
        if metodo == "GET":
            return {
                "state": [[{"id": "MG", "text": "Minas Gerais"}, {"id": "SE", "text": "Sergipe"}]],
                "city": [[{"id": "3100000", "text": "Cidade de exemplo (MG)"},
                          {"id": "2802106", "text": "Estância - SE"}]],
                "country": [[{"id": "063", "text": "País de exemplo"}]],
            }[url.rsplit("/", 1)[1]]
        consulta = opcoes["json"]
        self.assertEqual(consulta["filters"], [{"filter": "state", "values": ["MG"]},
                                               {"filter": "city", "values": ["3100000"]}])
        self.assertTrue(consulta["monthDetail"])
        ano, inicio = consulta["period"]["from"].split("-")
        fim = consulta["period"]["to"]
        self.assertEqual((inicio, fim[:4]), ("01", ano))
        return {"list": [{"year": ano, "monthNumber": mes, "noMunMinsgUf": "Cidade de exemplo - MG",
                          "headingCode": "901", "country": "País de exemplo",
                          "metricFOB": 10, "metricKG": 3} for mes in range(1, int(fim[-2:]) + 1)]}

    def test_um_post_por_ano_cache_e_corte(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(comex, "BRUTOS", Path(pasta)), \
                patch.object(comex, "consultar_api", side_effect=self.resposta) as api:
            primeiro = comex.obter_arquivos(2015, 12)
            self.assertEqual(comex.obter_arquivos(2015, 12), primeiro)
            segundo = comex.obter_arquivos(2016, 10)
            self.assertEqual([c.args[0] for c in api.call_args_list].count("POST"), 2)
            self.assertEqual([c.args[0] for c in api.call_args_list].count("GET"), 3)
            dados = comex.ler_e_tratar(segundo, 2016)
            self.assertEqual(len(dados), 10)
            self.assertEqual(dados.iloc[-1][comex.COLUNAS].tolist(),
                             [2016, 10, "0901", "063", "MG", "3100000", 3, 10])

    def test_retornos_invalidos_preservam_lote(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(comex, "BRUTOS", Path(pasta)), \
                patch.object(comex, "consultar_api", side_effect=self.resposta) as api:
            destino = comex.obter_arquivos(2015, 2)
            original = destino.read_bytes()
            for campo, valor, erro in [("noMunMinsgUf", "Estância - SE", "rejeitado"),
                                       ("monthNumber", 2, "incompleta"), ("metricKG", -1, "negativas")]:
                def alterar(*args, **kwargs):
                    dados = self.resposta(*args, **kwargs)
                    dados["list"][0][campo] = valor
                    return dados
                api.side_effect = alterar
                with self.subTest(campo=campo), self.assertRaisesRegex(ValueError, erro):
                    comex.obter_arquivos(2015, 2, atualizar=True)
                self.assertEqual(destino.read_bytes(), original)

    def test_revisao_anual_preserva_versao_original(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(comex, "BRUTOS", Path(pasta)), \
                patch.object(comex, "consultar_api", side_effect=self.resposta) as api:
            destino = comex.obter_arquivos(2015, 1)
            original = destino.read_bytes()
            def revisao(*args, **kwargs):
                dados = self.resposta(*args, **kwargs)
                dados["list"][0]["metricKG"] = 9
                return dados
            api.side_effect = revisao
            comex.obter_arquivos(2015, 1, atualizar=True)
            self.assertNotEqual(destino.read_bytes(), original)
            self.assertEqual([p.read_bytes() for p in (destino.parent / "versoes").glob("*.csv")], [original])
