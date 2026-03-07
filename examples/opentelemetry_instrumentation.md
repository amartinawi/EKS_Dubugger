# OpenTelemetry Instrumentation Example

This example shows how to add OpenTelemetry tracing to the EKS debugger.

## Installation

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
```

## Usage

Add this to `eks_comprehensive_debugger.py`:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Setup tracing (optional)
def setup_telemetry():
    """Setup OpenTelemetry tracing."""
    provider = TracerProvider()
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return trace.get_tracer(__name__)

# Instrument analysis methods
tracer = setup_telemetry() if os.getenv("ENABLE_TRACING") == "true" else None

class ComprehensiveEKSDebugger:
    def analyze_pod_health_deep(self):
        """Analyze pod health with tracing."""
        if tracer:
            with tracer.start_as_current_span("analyze_pod_health") as span:
                span.set_attribute("cluster", self.cluster_name)
                span.set_attribute("region", self.region)
                # ... existing code ...
        else:
            # ... existing code without tracing ...
```

## Environment Variables

```bash
export ENABLE_TRACING=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=eks-debugger
```

## Running with Tracing

```bash
ENABLE_TRACING=true python eks_comprehensive_debugger.py --profile prod --region us-east-1
```

## Viewing Traces

Use Jaeger, Zipkin, or AWS X-Ray to visualize traces:

```bash
# Jaeger (local)
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  jaegertracing/all-in-one:latest

# Open http://localhost:16686 to view traces
```

## Benefits

- **Performance analysis**: Identify slow analysis methods
- **Error tracking**: See which methods fail and why
- **Dependency mapping**: Understand AWS API call patterns
- **Production debugging**: Trace issues in automated runs
