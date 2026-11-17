import pytest
from atlas_core.instalacion_motor_segura import Proceso, procesos_del_motor, instalar_con_recuperacion, RecuperacionIncompleta


class Simulador:
    def __init__(self, falla=None):
        self.falla = falla
        self.tareas = {"pull": True, "mantenimiento": True}
        self.journal = None
        self.guardia = False
        self.instalado = False
        self.interlock = False
        self.ciclo_en_curso = True
        self.eventos = []
    def paso(self, nombre):
        self.eventos.append(nombre)
        if self.falla == nombre:
            raise RuntimeError(nombre)
        if self.falla == "interrupcion_" + nombre:
            raise KeyboardInterrupt(nombre)
    def preparar(self): self.paso("preparar")
    def tareas_activas(self): return [k for k,v in self.tareas.items() if v]
    def registrar_recuperacion(self, tareas): self.journal = tuple(tareas); self.paso("journal")
    def armar_guardia(self, tareas): self.guardia = True; self.paso("armar")
    def comprobar_guardia(self): return self.falla != "sin_guardia"
    def pausar(self, tarea): self.tareas[tarea] = False; self.paso("pausar_"+tarea)
    def esperar_ciclos(self): self.paso("esperar"); self.ciclo_en_curso = False
    def adquirir_interlock(self): self.paso("adquirir"); self.interlock = True
    def comprobar_exclusividad(self): self.paso("exclusividad"); assert self.interlock and not self.ciclo_en_curso
    def instalar(self): self.paso("instalar"); self.instalado = True
    def comprobar_motor_recuperable(self): self.paso("motor_recuperable")
    def liberar_interlock(self): self.paso("liberar"); self.interlock = False
    def reactivar(self, tarea): self.paso("reactivar_"+tarea); self.tareas[tarea] = True
    def activa(self, tarea): return self.tareas[tarea]
    def verificar_continuidad(self, tareas): self.paso("continuidad"); assert all(self.tareas[t] for t in tareas)
    def cerrar_recuperacion(self): self.paso("cerrar"); self.guardia = False; self.journal = None


def test_identifica_motor_e_hijos_sin_confundir_otras_pruebas():
    motor = r"C:\Atlas\Proyecto-Atlas"
    procesos = [Proceso(1, 0, ("python", motor + r"\sincronizar_mobile_cloud.py")),
        Proceso(2, 1, ("python", r"C:\runtime\rapidocr_worker.py")),
        Proceso(3, 0, (r"C:\Atlas\Proyecto-Atlas\.venv\Scripts\python.exe", "-m", "pytest")),
        Proceso(4, 3, ("python", r"C:\Atlas\pruebas\claude\motor\prueba.py")),
        Proceso(5, 0, ("python", r"C:\Atlas\Proyecto-Atlas-otro\sincronizar.py"))]
    assert procesos_del_motor(procesos, motor) == {1, 2}


def test_flujo_espera_ciclo_y_reactiva():
    s = Simulador(); instalar_con_recuperacion(s)
    assert s.instalado and all(s.tareas.values()) and not s.guardia and s.journal is None
    assert s.eventos.index("esperar") < s.eventos.index("instalar") < s.eventos.index("continuidad")


@pytest.mark.parametrize("punto", ["pausar_pull", "pausar_mantenimiento", "esperar", "adquirir", "exclusividad", "instalar", "interrupcion_instalar"])
def test_error_o_interrupcion_restaura_todas_las_tareas(punto):
    s = Simulador(punto)
    with pytest.raises((RuntimeError, KeyboardInterrupt)): instalar_con_recuperacion(s)
    assert all(s.tareas.values()) and not s.guardia and s.journal is None
    assert not s.interlock


def test_no_inicia_sin_guardia():
    s = Simulador("sin_guardia")
    with pytest.raises(RuntimeError): instalar_con_recuperacion(s)
    assert all(s.tareas.values()) and not s.instalado
    assert s.journal == ("pull", "mantenimiento")


@pytest.mark.parametrize("punto", ["reactivar_pull", "continuidad", "liberar"])
def test_no_declara_exito_ante_recuperacion_incompleta(punto):
    s = Simulador(punto)
    with pytest.raises(RecuperacionIncompleta): instalar_con_recuperacion(s)
    assert s.guardia and s.journal is not None


def test_codigo_incompleto_no_reanuda_pull():
    s = Simulador("motor_recuperable")
    with pytest.raises(RecuperacionIncompleta): instalar_con_recuperacion(s)
    assert not any(s.tareas.values()) and s.guardia and s.journal is not None
