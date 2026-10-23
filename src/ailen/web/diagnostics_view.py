"""Render real diagnostics DTOs without interpreting missing data as success."""

from ailen.services.diagnostics_admin_service import DiagnosticsSnapshot
from ailen.web.templates import render


def diagnostics_content(snapshot: DiagnosticsSnapshot, csrf: str) -> str:
    checks = "".join(render("diagnostics_check.html", name=c.name, result=c.result)
                     for c in snapshot.checks)
    components = "".join(render("diagnostics_check.html", name=name, result=value)
                         for name, value in snapshot.components)
    rows = "".join(render(
        "diagnostics_metric.html", label=row.label, samples=row.samples,
        average=f"{row.average_ms:.1f} ms" if row.average_ms is not None else "Sin medición",
        p95=f"{row.p95_ms:.1f} ms" if row.p95_ms is not None else "Sin medición",
    ) for row in snapshot.telemetry.rows)
    if not rows:
        rows = '<tr><td colspan="4">Sin medición verificable disponible.</td></tr>'
    telemetry_copy = {
        "NO_DATA": "Todavía no hay un reporte de sesión finalizada.",
        "RECORDED": "Última sesión finalizada con backends reales. No es telemetría en vivo ni certificación de hardware.",
        "UNVERIFIED": "El último reporte es simulado o no declara su procedencia; no se presenta como medición real.",
        "UNAVAILABLE": "No se pudo leer un reporte válido de la última sesión.",
    }
    return render(
        "diagnostics.html", csrf=csrf, health=snapshot.health,
        assistant_state=snapshot.assistant_state, checked_at=snapshot.checked_at or "Sin consulta",
        components=components or '<li>Estado no disponible.</li>',
        doctor_state="Sin ejecutar" if snapshot.doctor_state == "NOT_RUN" else snapshot.doctor_state,
        doctor_checked_at=snapshot.doctor_checked_at or "Sin ejecución previa",
        checks=checks or '<li>Sin resultados de comprobación.</li>',
        metrics=rows, telemetry_detail=telemetry_copy.get(snapshot.telemetry.state, "Sin medición"),
        telemetry_timestamp=snapshot.telemetry.ended_at or "Sin fecha de medición",
    )
