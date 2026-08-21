# Benchmark de Presencia Física y Face — AILEN R2A

> **ADVERTENCIA OBLIGATORIA:**  
> **DEV MACHINE — NO HARDWARE TARGET**  
> Estas mediciones fueron ejecutadas en la máquina de desarrollo (`x86_64`, Linux `7.0.0-28-generic`).  
> **NO constituyen benchmark ni validación en hardware objetivo** (Banghó Zero G05 / SF20BA). Las pruebas en dichos dispositivos permanecen pendientes de ejecución física.

**Fecha de ejecución:** `2026-08-21T19:31:22Z`

---

## 1. FaceAnimator (Motor Lógico de Rostro)

Calcula poses normalizadas, parpadeo natural no periódico, interpolación suave de mirada y apertura de boca.

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | 5000 |
| **Tiempo total** | 0.0311 s |
| **Throughput** | **160684.7 FPS** (modo unconstrained) |
| **Frame Time Promedio** | **6.02 µs** (0.006 ms) |
| **Frame Time p50** | 3.59 µs |
| **Frame Time p95** | 4.4 µs |
| **Frame Time p99** | 5.49 µs |
| **Peak RSS del proceso (inicio → fin)** | 72.29 → 72.29 MB |
| **Δ peak RSS durante la prueba** | 0.0 MB |

*Interpretación Face:* esta medición cubre sólo costo de cómputo del `FaceAnimator`; el RSS corresponde al **proceso Python completo**, no a memoria atribuible exclusivamente al rostro. El uso de CPU a 30 FPS debe medirse por separado en hardware objetivo.

---

## 2. VisionDebouncer (Filtro Temporal de Presencia)

Filtra oscilaciones rápidas y confirma presencia/ausencia estable según ventana temporal.

| Métrica | Valor |
| :--- | :--- |
| **Iteraciones** | 10000 |
| **Throughput** | **1666440.3 updates/segundo** |
| **Latencia Promedio** | **0.42 µs** |
| **Latencia p50** | 0.32 µs |
| **Latencia p95** | 1.29 µs |

---

## 3. Pipeline Integrado (Visión → Debouncer → Coordinator → Social → Face)

Ciclo completo de presencia física: actualización de visión, debounce temporal, transición de estados en `StateManager`, evaluación en `SocialEngine` y emisión de pose en `FaceAnimator`.

| Métrica | Valor |
| :--- | :--- |
| **Ciclos evaluados** | 3000 |
| **Throughput integrado** | **89991.6 ciclos/segundo** |
| **Tiempo por ciclo promedio** | **10.87 µs** (0.011 ms) |
| **Tiempo por ciclo p50** | 12.4 µs |
| **Tiempo por ciclo p95** | 18.22 µs |

*Interpretación General:* este benchmark mide overhead lógico del Core/Social/Face en la máquina DEV. No mide captura OpenCV real, render gráfico real ni audio/STT, y **no permite inferir todavía porcentajes de CPU ni latencia en Banghó/SF20BA**.
