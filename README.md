# Climate Observations

Servicio de datos para las **121 estaciones operativas** asociadas a las
10.601 localidades del catálogo ClimateProyectar.

- Consulta siempre todas las estaciones.
- Pausa de 1,5 segundos entre consultas.
- Conserva el último dato válido ante fallos temporales.
- Publica JSON estático en `/docs`.

## GitHub Pages

Configurar Pages desde `main` y `/docs`.

## Cron externo

Horario recomendado:

```cron
0,20,40 * * * *
```

Cuerpo:

```json
{
  "ref": "main"
}
```

Endpoint:

```text
https://api.github.com/repos/mtgproyect/climate-observations/actions/workflows/actualizar-observaciones.yml/dispatches
```
