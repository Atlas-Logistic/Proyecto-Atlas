from unittest.mock import patch
from atlas_core import estado_confirmado as ec
from atlas_core.escritor_operativo import ErrorEscritorOperativo
from test_estado_confirmado import CloudFalsa, Equipo
import pytest

def test_expiracion_remota_no_invalida_propiedad_local_hasta_heartbeat(tmp_path):
    cloud = CloudFalsa(); equipo = Equipo(tmp_path, 'casa', cloud)
    with patch('atlas_core.escritor_operativo._json', side_effect=cloud.json), patch.object(ec.ClienteEstado, '_crudo', lambda c,h,**kw: cloud.crudo(c,h,**kw)):
        with equipo.lease() as lease:
            assert lease.adquirir()
            cloud.avanzar(3)
            assert lease.vigente  # Estado local aun no conoce expiracion remota.
            with pytest.raises(ErrorEscritorOperativo):
                lease.custodia.cliente.confirmar(lease.lease_token, 0, [['x.txt', None]])
            assert not lease.renovar()
            assert not lease.vigente
