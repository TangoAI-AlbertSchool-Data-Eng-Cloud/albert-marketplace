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
