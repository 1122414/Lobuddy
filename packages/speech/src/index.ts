// Speech runs independently from the business service and receives no provider credentials.
export { VoiceFrameSchema, VoiceOptionsSchema, VoiceStatusSchema, VoiceEventSchema } from '@lobuddy/contracts';
export type { VoiceFrame, VoiceOptions, VoiceStatus, VoiceEvent } from '@lobuddy/contracts';
export { SpeechClient } from './client.js';
export type { SpeechTransport } from './client.js';
export type { SpeechDriver, SpeechEvent, SpeechCommand } from './protocol.js';
export { SpeechEventSchema, SpeechCommandSchema, SpeechReplySchema } from './protocol.js';
export { modelsReady, downloadModels } from './models.js';
export { AudioSession } from './recognizer.js';
export type { AudioRecognizer } from './recognizer.js';
