import "dotenv/config";
import { readFileSync } from "fs";
import { resolve } from "path";

import { ServiceBusClient, ServiceBusMessage } from "@azure/service-bus";

interface AudioProcessingMessage {
  callId: string;
  audioUrl?: string;
  timestamp: string;
  ringcentralData: Record<string, unknown>;
  priority?: string;
}

function loadMessageFromFile(filePath: string): AudioProcessingMessage {
  const absolute = resolve(process.cwd(), filePath);
  const raw = readFileSync(absolute, "utf-8");
  const parsed = JSON.parse(raw);
  if (!parsed.callId && !parsed.call_id) {
    throw new Error("Message file must include 'callId'");
  }
  return {
    callId: String(parsed.callId ?? parsed.call_id),
    audioUrl: parsed.audioUrl ?? parsed.recordingUrl,
    timestamp: parsed.timestamp ?? new Date().toISOString(),
    ringcentralData: parsed.ringcentralData ?? parsed.ringcentral_data ?? {},
    priority: parsed.priority,
  };
}

function buildSampleMessage(): AudioProcessingMessage {
  return {
    callId: `sample-call-${Date.now()}`,
    audioUrl: "https://example.com/audio.mp3",
    timestamp: new Date().toISOString(),
    ringcentralData: {
      webhook: "sample",
      note: "Replace with real RingCentral payload",
    },
    priority: "normal",
  };
}

function getEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} environment variable is required`);
  }
  return value;
}

async function sendMessage(message: AudioProcessingMessage): Promise<void> {
  const dryRun = process.env.DRY_RUN === "1" || process.env.DRY_RUN === "true";
  if (dryRun) {
    console.log("[dry-run] Would send message:", JSON.stringify(message, null, 2));
    return;
  }

  const connectionString = getEnv("AZURE_SERVICEBUS_CONNECTION_STRING");
  const queueName = getEnv("AZURE_SERVICEBUS_QUEUE_NAME");

  const client = new ServiceBusClient(connectionString);
  const sender = client.createSender(queueName);

  const sbMessage: ServiceBusMessage = {
    body: message,
    contentType: "application/json",
    applicationProperties: {
      priority: message.priority ?? "normal",
    },
    subject: "audio-processing",
  };

  try {
    await sender.sendMessages(sbMessage);
    console.log(`Sent message for callId=${message.callId}`);
  } finally {
    await sender.close();
    await client.close();
  }
}

async function main(): Promise<void> {
  const filePath = process.argv[2];
  const message = filePath ? loadMessageFromFile(filePath) : buildSampleMessage();
  await sendMessage(message);
}

if (require.main === module) {
  main().catch((err) => {
    console.error("Failed to send Service Bus message", err);
    process.exitCode = 1;
  });
}
