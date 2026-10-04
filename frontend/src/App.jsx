import { useState } from "react";
import {
  Activity,
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock,
  Send,
  UserRound,
} from "lucide-react";

import { sendMessage } from "./services/api";
import "./App.css";


function App() {
  const [threadId] = useState(
    () =>
      localStorage.getItem("scheduling_thread_id") ||
      crypto.randomUUID()
  );

  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "Hello! I can help you find a doctor and schedule an appointment. What would you like to do?",
    },
  ]);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [trace, setTrace] = useState([]);
  const [status, setStatus] = useState("ready");

  const [appointment, setAppointment] = useState({
    doctor: "",
    date: "",
    time: "",
    patient: "",
  });

  const saveThreadId = () => {
    localStorage.setItem(
      "scheduling_thread_id",
      threadId
    );
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (!input.trim() || loading) {
      return;
    }

    const userMessage = {
      role: "user",
      content: input,
    };

    setMessages((previous) => [
      ...previous,
      userMessage,
    ]);

    const query = input;
    setInput("");
    setLoading(true);

    try {
      saveThreadId();

      const result = await sendMessage(
        query,
        threadId
      );

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: result.response,
        },
      ]);

      setTrace(result.trace || []);
      setStatus(result.status || "completed");

      updateAppointmentFromTrace(
        result.trace || []
      );
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            "Sorry, I couldn't connect to the scheduling service.",
        },
      ]);

      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const updateAppointmentFromTrace = (items) => {
    const analyzeNodes = items.filter(
      (item) =>
        item.node === "analyze_request"
    );

    if (!analyzeNodes.length) {
      return;
    }

    try {
      const latest =
        JSON.parse(
          analyzeNodes[
            analyzeNodes.length - 1
          ].details
        );

      setAppointment((previous) => ({
        doctor:
          latest.doctor_name ||
          previous.doctor,

        date:
          latest.appointment_date ||
          previous.date,

        time:
          latest.appointment_time ||
          previous.time,

        patient:
          latest.patient_name ||
          previous.patient,
      }));
    } catch {
      // Ignore malformed trace entries.
    }
  };

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-icon">
            <Activity size={22} />
          </div>

          <div>
            <h1>CareFlow AI</h1>
            <p>Agentic Healthcare Scheduling</p>
          </div>
        </div>

        <div className="status-indicator">
          <span />
          Agent Online
        </div>
      </header>

      <main className="dashboard">
        <section className="chat-section">
          <div className="section-header">
            <div>
              <h2>Scheduling Assistant</h2>
              <p>
                Talk naturally with the AI scheduling agent.
              </p>
            </div>

            <Bot size={24} />
          </div>

          <div className="messages">
            {messages.map((message, index) => (
              <div
                key={index}
                className={`message ${message.role}`}
              >
                <div className="message-icon">
                  {message.role === "assistant" ? (
                    <Bot size={17} />
                  ) : (
                    <UserRound size={17} />
                  )}
                </div>

                <div className="message-content">
                  {message.content}
                </div>
              </div>
            ))}

            {loading && (
              <div className="message assistant">
                <div className="message-icon">
                  <Bot size={17} />
                </div>

                <div className="message-content">
                  Agent is processing...
                </div>
              </div>
            )}
          </div>

          <form
            className="input-area"
            onSubmit={handleSubmit}
          >
            <input
              value={input}
              onChange={(event) =>
                setInput(event.target.value)
              }
              placeholder="e.g. I need to see a neurologist..."
              disabled={loading}
            />

            <button
              type="submit"
              disabled={
                loading || !input.trim()
              }
            >
              <Send size={18} />
            </button>
          </form>
        </section>

        <aside className="sidebar">
          <AppointmentCard
            appointment={appointment}
            status={status}
          />

          <TracePanel trace={trace} />
        </aside>
      </main>
    </div>
  );
}


function AppointmentCard({
  appointment,
  status,
}) {
  const confirmed =
    status === "confirmed";

  return (
    <div className="card appointment-card">
      <div className="card-title">
        <CalendarDays size={20} />
        <h3>Appointment</h3>
      </div>

      <div className="appointment-info">
        <InfoRow
          icon={<UserRound size={17} />}
          label="Doctor"
          value={
            appointment.doctor ||
            "Not selected"
          }
        />

        <InfoRow
          icon={<CalendarDays size={17} />}
          label="Date"
          value={
            appointment.date ||
            "Not selected"
          }
        />

        <InfoRow
          icon={<Clock size={17} />}
          label="Time"
          value={
            appointment.time ||
            "Not selected"
          }
        />

        <InfoRow
          icon={<UserRound size={17} />}
          label="Patient"
          value={
            appointment.patient ||
            "Not selected"
          }
        />
      </div>

      {confirmed && (
        <div className="confirmed">
          <CheckCircle2 size={17} />
          Appointment Confirmed
        </div>
      )}
    </div>
  );
}


function InfoRow({
  icon,
  label,
  value,
}) {
  return (
    <div className="info-row">
      <div className="info-icon">
        {icon}
      </div>

      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}


function TracePanel({ trace }) {
  return (
    <div className="card trace-card">
      <div className="card-title">
        <Activity size={20} />
        <h3>Agent Execution</h3>
      </div>

      {trace.length === 0 ? (
        <p className="empty-trace">
          Workflow execution will appear here.
        </p>
      ) : (
        <div className="trace-list">
          {trace.map((item, index) => (
            <div
              className="trace-item"
              key={index}
            >
              <div className="trace-dot" />

              <div>
                <strong>
                  {item.node}
                </strong>

                <p>
                  {item.details}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


export default App;