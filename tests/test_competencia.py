import json
import unittest

from olist_competencia.cambios import Cambio, cargar_catalogo, enviar, restaurar, validar
from olist_competencia.credenciales import leer_csv


class Catalogo(unittest.TestCase):
    def setUp(self):
        self.cat = cargar_catalogo()

    def test_estructura(self):
        self.assertEqual(len(self.cat["productos"]), 48)
        self.assertEqual(sorted(self.cat["tiendas"]), ["compree", "mercadoabierto", "ridley", "selva"])

    def test_validacion(self):
        sku = next(iter(self.cat["tiendas"]["selva"]["productos"]))
        olist = next(p["precio_olist"] for p in self.cat["productos"] if p["sku"] == sku)
        self.assertEqual(validar(Cambio("selva", sku, "precio", olist * 0.9), self.cat), ([], []))
        errores, avisos = validar(Cambio("selva", sku, "precio", olist * 3), self.cat)
        self.assertEqual(errores, [])
        self.assertIn("R9", avisos[0])
        self.assertTrue(validar(Cambio("selva", sku, "descuento", 95), self.cat)[0])
        self.assertTrue(validar(Cambio("selva", "OL-9999", "agotar"), self.cat)[0])
        self.assertEqual(validar(restaurar(), self.cat), ([], []))

    def test_mensaje(self):
        m = Cambio("ridley", "OL-0001", "agotar", valor=10, autor="ana").mensaje()
        self.assertNotIn("valor", m)
        self.assertEqual(m["accion"], "agotar")
        self.assertEqual(restaurar().mensaje()["accion"], "restaurar")


class EnvioFifo(unittest.TestCase):
    def test_grupo_y_deduplicacion(self):
        enviados = []

        class Sqs:
            def send_message(self, **kw):
                enviados.append(kw)
                return {"MessageId": "m1"}

        class Sesion:
            def client(self, _):
                return Sqs()

        class Conexion:
            session, url_cola = Sesion(), "https://cola"

        c = Cambio("selva", "OL-0001", "precio", 10.0)
        self.assertEqual(enviar(Conexion(), c), "m1")
        self.assertEqual(enviados[0]["MessageDeduplicationId"], c.cambio_id)
        self.assertEqual(json.loads(enviados[0]["MessageBody"])["valor"], 10.0)
        self.assertTrue(c.enviado_en)


class Credenciales(unittest.TestCase):
    def test_csv(self):
        csv = b"Access key ID,Secret access key\nAKIAABCDEFGHIJKLMNOP," + b"x" * 40 + b"\n"
        cred = leer_csv(csv)
        self.assertNotIn("x" * 10, repr(cred))
        with self.assertRaises(ValueError):
            leer_csv(b"a,b\n1,2\n")


if __name__ == "__main__":
    unittest.main()
