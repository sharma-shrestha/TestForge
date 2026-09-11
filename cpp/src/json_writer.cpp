// json_writer.cpp

#include "testforge/json_writer.hpp"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>

namespace testforge {

JsonWriter::JsonWriter(std::ostream& out) : out_(out) {}

static std::string escape_json(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 8);
    for (char c : s) {
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b";  break;
            case '\f': out += "\\f";  break;
            case '\n': out += "\\n";  break;
            case '\r': out += "\\r";  break;
            case '\t': out += "\\t";  break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out.push_back(c);
                }
        }
    }
    return out;
}

void JsonWriter::key(const std::string& k) {
    out_ << '"' << escape_json(k) << '"' << ':';
}
void JsonWriter::string(const std::string& s) {
    out_ << '"' << escape_json(s) << '"';
}
void JsonWriter::number(double d)  { out_ << d; }
void JsonWriter::integer(long n)   { out_ << n; }
void JsonWriter::boolean(bool b)   { out_ << (b ? "true" : "false"); }
void JsonWriter::null()            { out_ << "null"; }

static std::string iso8601(std::chrono::system_clock::time_point tp) {
    std::time_t t = std::chrono::system_clock::to_time_t(tp);
    std::tm tm{};
    gmtime_r(&t, &tm);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tm);
    return buf;
}

void JsonWriter::write_result(const TestResult& r) {
    out_ << '{';
    key("test_name");          string(r.test_name);          out_ << ',';
    key("suite");             string(r.suite);              out_ << ',';
    key("status");            string(to_string(r.status));  out_ << ',';
    key("attempts");          integer(r.attempts);          out_ << ',';
    key("duration_ms");        number(r.duration_ms);        out_ << ',';
    key("failure_message");   string(r.failure_message);    out_ << ',';
    key("failure_file");      string(r.failure_file);       out_ << ',';
    key("failure_line");      integer(r.failure_line);       out_ << ',';
    key("stack_trace");       string(r.stack_trace);        out_ << ',';
    key("error_signature");   string(r.error_signature);    out_ << ',';

    key("peak_rss_kb");        r.peak_rss_kb           < 0 ? null() : integer(r.peak_rss_kb);            out_ << ',';
    key("cpu_user_ms");        r.cpu_user_ms           < 0 ? null() : number(r.cpu_user_ms);             out_ << ',';
    key("cpu_sys_ms");         r.cpu_sys_ms            < 0 ? null() : number(r.cpu_sys_ms);              out_ << ',';
    key("gpu_utilization_pct"); r.gpu_utilization_pct < 0 ? null() : number(r.gpu_utilization_pct);     out_ << ',';
    key("gpu_memory_used_mb");  r.gpu_memory_used_mb  < 0 ? null() : integer(r.gpu_memory_used_mb);     out_ << ',';
    key("gpu_kernel_latency_ms"); r.gpu_kernel_latency_ms < 0 ? null() : number(r.gpu_kernel_latency_ms); out_ << ',';
    key("gpu_device_name");   string(r.gpu_device_name);   out_ << ',';

    key("assertions"); out_ << '[';
    for (size_t i = 0; i < r.assertions.size(); ++i) {
        const auto& a = r.assertions[i];
        out_ << '{';
        key("condition"); string(a.condition);    out_ << ',';
        key("file");      string(a.file);        out_ << ',';
        key("line");      integer(a.line);       out_ << ',';
        key("passed");    boolean(a.passed);     out_ << ',';
        key("message");   string(a.message);
        out_ << '}';
        if (i + 1 < r.assertions.size()) out_ << ',';
    }
    out_ << ']';
    out_ << '}';
}

void JsonWriter::write_report(const RunReport& r) {
    out_ << '{';
    key("worker_id");   string(r.worker_id);          out_ << ',';
    key("started_at");  string(iso8601(r.started_at)); out_ << ',';
    key("finished_at"); string(iso8601(r.finished_at)); out_ << ',';
    key("ok");          boolean(r.ok);                out_ << ',';
    key("error");       string(r.error);              out_ << ',';
    key("results");    out_ << '[';
    for (size_t i = 0; i < r.results.size(); ++i) {
        write_result(r.results[i]);
        if (i + 1 < r.results.size()) out_ << ',';
    }
    out_ << ']';
    out_ << '}';
}

} // namespace testforge
