# Step 7: the Kafka broker in its own compose project: listeners, topic, memory, persistence.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step7'
$env:KAFKA_PORT = '39092'
$env:KAFKA_DOCKER_PORT = '39093'
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated|Restarting)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Kafka([string]$Tool, [string[]]$ToolArgs) {
    docker compose exec -T kafka "/opt/kafka/bin/$Tool" @ToolArgs 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch 'WARN|^\s*$' | ForEach-Object { "$_" }
}
function WaitHealthy {
    for ($i = 0; $i -lt 60; $i++) {
        if ((docker inspect -f "{{.State.Health.Status}}" am-step7-kafka-1 2>$null) -eq 'healthy') { return "healthy after ~$($i * 2) s" }
        Start-Sleep -Seconds 2
    }
    return "NOT healthy"
}
function Offsets { (Kafka 'kafka-get-offsets.sh' @('--bootstrap-server', 'kafka:9092', '--topic', 'clickstream')) -join ' ' }

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is not running"; exit 1 }

"=== 1. start kafka and kafka-init"
Dc --profile build down -v
$sw = [Diagnostics.Stopwatch]::StartNew()
Dc up -d kafka-init
"kafka: " + (WaitHealthy)
for ($i = 0; $i -lt 60; $i++) {
    $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step7-kafka-init-1 2>$null
    if ($st -like 'exited*') { break }
    Start-Sleep -Seconds 2
}
"kafka-init: $st after $([int]$sw.Elapsed.TotalSeconds) s"
Dc logs --no-color kafka-init
"broker log errors: " + @(docker compose logs --no-color kafka 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern ' ERROR |Exception').Count
docker compose logs --no-color kafka 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'heap|Xmx|Kafka version|started \(kafka.server' | Select-Object -First 4 | ForEach-Object { "  $_" }

"=== 2. topic"
Kafka 'kafka-topics.sh' @('--bootstrap-server', 'kafka:9092', '--describe', '--topic', 'clickstream')
Start-Sleep -Seconds 15
"memory idle: " + (docker stats --no-stream --format "{{.MemUsage}}" am-step7-kafka-1)

"=== 3. 200,000 messages of 400 bytes through the internal listener"
Kafka 'kafka-producer-perf-test.sh' @('--topic', 'clickstream', '--num-records', '200000', '--record-size', '400', '--throughput', '-1', '--command-property', 'bootstrap.servers=kafka:9092') | Select-Object -Last 1
"offsets: " + (Offsets)
"memory after the load: " + (docker stats --no-stream --format "{{.MemUsage}}" am-step7-kafka-1)
"data directory: " + (docker compose exec -T kafka du -sh /var/lib/kafka/data 2>&1)

"=== 4. listener for other Docker setups: host.docker.internal:39093, from a container outside this project"
"hello from another container" | docker run --rm -i apache/kafka:4.3.1 /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server host.docker.internal:39093 --topic clickstream 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch 'WARN|^\s*$'
docker run --rm apache/kafka:4.3.1 /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server host.docker.internal:39093 --topic clickstream 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch 'WARN|^\s*$'

"=== 5. host listener: localhost:39092, from Python on Windows (kafka-python, pure Python)"
$py = @'
import sys
from kafka import KafkaConsumer, KafkaProducer, TopicPartition
server = sys.argv[1]
producer = KafkaProducer(bootstrap_servers=server)
producer.send("clickstream", key=b"host", value=b"hello from the host").get(timeout=30)
producer.close()
consumer = KafkaConsumer(bootstrap_servers=server)
partitions = [TopicPartition("clickstream", p) for p in sorted(consumer.partitions_for_topic("clickstream"))]
ends = consumer.end_offsets(partitions)
print("host client: topics", sorted(consumer.topics()), "| end offsets", {tp.partition: o for tp, o in ends.items()}, "| total", sum(ends.values()))
consumer.close()
'@
$py | Out-File -Encoding ascii "$S\step7_host_client.py"
uv run --no-project --quiet --with kafka-python python "$S\step7_host_client.py" "localhost:39092" 2>&1 | ForEach-Object { "$_" }

"=== 6. persistence"
$before = Offsets
Dc restart kafka
"after restart: " + (WaitHealthy) + " | offsets unchanged: " + ((Offsets) -eq $before)
Dc stop
Dc up -d kafka
"after stop and up: " + (WaitHealthy) + " | offsets unchanged: " + ((Offsets) -eq $before)
"offsets: $before"

"=== 7. tear down"
Dc --profile build down -v
