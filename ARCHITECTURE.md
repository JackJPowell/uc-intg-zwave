# Architecture Overview - Z-Wave Integration

This document provides a comprehensive overview of the Z-Wave integration architecture, explaining how all components work together.

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                   Unfolded Circle Remote                     │
│                    (User Interface)                          │
└────────────────────┬────────────────────────────────────────┘
                     │ UC API Commands
                     │ (HTTP/WebSocket)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Integration Driver                        │
│                      (driver.py)                             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  - Entity Registration & Management                    │ │
│  │  - Command Routing (lights, covers, buttons)          │ │
│  │  - Event Subscriptions                                │ │
│  │  - Connection Lifecycle (connect/disconnect/standby)  │ │
│  │  - Performance Tracking                               │ │
│  └────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Z-Wave Bridge                             │
│                     (bridge.py)                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  - SmartHub (Controller Interface)                    │ │
│  │  - Connection Management                              │ │
│  │  - Event Handler Setup/Teardown                      │ │
│  │  - Watchdog Process (Auto-reconnect)                 │ │
│  │  - Device Queries (get_lights, get_covers)           │ │
│  │  - Command Execution (control_light, control_cover)   │ │
│  └────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   Z-Wave Client                              │
│                  (zwave_client.py)                           │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  - WebSocket Connection to Z-Wave JS Server           │ │
│  │  - Message Queue (async send/receive)                 │ │
│  │  - Event Dispatching                                  │ │
│  │  - API Methods (get_nodes, set_value, etc.)          │ │
│  │  - Controller Info Retrieval                          │ │
│  └────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │ WebSocket (ws://)
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Z-Wave JS Server                            │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  - Z-Wave Protocol Implementation                     │ │
│  │  - Node Management                                    │ │
│  │  - Command Class Handling                             │ │
│  │  - Network Mesh Management                            │ │
│  └────────────────────────────────────────────────────────┘ │
└────────────────────┬────────────────────────────────────────┘
                     │ Serial/USB
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  Z-Wave USB Stick                            │
│              (Aeotec, Zooz, etc.)                            │
└────────────────────┬────────────────────────────────────────┘
                     │ Z-Wave RF
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   Z-Wave Devices                             │
│       (Lights, Covers, Switches, Sensors, etc.)              │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Integration Driver (`driver.py`)

**Purpose**: Main integration entry point, handles UC Remote API communication

**Key Responsibilities**:
- Initialize and manage Z-Wave bridge connections
- Register entities dynamically from Z-Wave network
- Route commands from UC Remote to appropriate handlers
- Manage entity subscriptions
- Handle connection lifecycle events
- Track performance metrics

**Key Classes**:
- `ZWaveDriver`: Main driver class

**Key Methods**:
```python
async def register_available_entities()    # Dynamic entity discovery
async def on_r2_connect_cmd()              # Remote connection handler
async def on_r2_disconnect_cmd()           # Remote disconnection handler
async def handle_light_command()           # Light command routing
async def handle_cover_command()           # Cover command routing
async def on_device_connected()            # Z-Wave controller connected
async def on_device_update()               # Entity state updates
```

**Performance Tracking**:
- All major methods decorated with `@track_performance`
- Slow call detection (>1s)
- Periodic reports every 5 minutes

---

### 2. Z-Wave Bridge (`bridge.py`)

**Purpose**: Interface between integration and Z-Wave network

**Key Responsibilities**:
- Establish/maintain WebSocket connection to Z-Wave JS Server
- Query Z-Wave devices and capabilities
- Execute commands on Z-Wave devices
- Monitor connection health with watchdog
- Handle event subscriptions
- Manage controller information

**Key Classes**:
- `SmartHub`: Main bridge class
- `EVENTS`: Event enumeration (CONNECTING, CONNECTED, DISCONNECTED, etc.)
- `PowerState`: Connection state enumeration

**Key Methods**:
```python
async def connect()                        # Establish connection
async def disconnect()                     # Close connection
async def get_lights()                     # Query light devices
async def get_covers()                     # Query cover devices
async def control_light()                  # Send light command
async def control_cover()                  # Send cover command
def get_controller_info()                  # Get controller metadata
async def _watchdog_loop()                 # Connection monitoring
async def _reconnect()                     # Auto-reconnection
```

**Watchdog Features**:
- Monitors connection every 30 seconds
- Automatic reconnection on failure
- Configurable intervals and delays
- Event emission on state changes

---

### 3. Z-Wave Client (`zwave_client.py`)

**Purpose**: Low-level WebSocket communication with Z-Wave JS Server

**Key Responsibilities**:
- Manage WebSocket connection lifecycle
- Send/receive messages with message IDs
- Dispatch events to registered handlers
- Provide high-level API for Z-Wave operations
- Handle connection errors and timeouts

**Key Classes**:
- `ZWaveClient`: Main client class

**Key Methods**:
```python
async def connect()                        # Open WebSocket connection
async def disconnect()                     # Close WebSocket connection
async def send_command()                   # Send command and wait for response
def get_controller_info()                  # Retrieve controller metadata
async def get_nodes()                      # Get all Z-Wave nodes
async def set_value()                      # Set a value on a node
def add_event_handler()                    # Register event listener
def remove_event_handler()                 # Unregister event listener
```

**Event Handling**:
- Event emitter pattern (pyee)
- Support for: value_updated, node_status_changed, etc.
- Thread-safe event dispatching
- Proper handler cleanup on disconnect

---

### 4. Entity Implementations

#### Light Entity (`light.py`)

**Features**:
- On/Off control
- Brightness (0-100%)
- State tracking
- Multi-level switch support

**Command Classes**:
- `SWITCH_BINARY`: On/Off switches
- `SWITCH_MULTILEVEL`: Dimmers

#### Cover Entity (`cover.py`)

**Features**:
- Open/Close/Stop commands
- Position control (0-100%)
- State tracking (opening/closing/stopped)
- Current position reporting

**Command Classes**:
- `SWITCH_MULTILEVEL`: Position control
- `BARRIER_OPERATOR`: Garage doors

#### Button Entity (`button.py`)

**Features**:
- Press, hold, release events
- Scene activation
- Multi-button devices

**Command Classes**:
- `CENTRAL_SCENE`: Scene controllers
- `SCENE_ACTIVATION`: Scene triggers

---

### 5. Configuration Management (`config.py`)

**Purpose**: Device configuration and entity ID generation

**Key Features**:
- Controller-based configuration (home_id)
- Unique entity ID generation
- Configuration persistence
- Metadata storage

**Key Functions**:
```python
def create_entity_id()                     # Generate unique entity ID
class ZWaveConfig                          # Configuration data class
```

**Entity ID Format**:
```
{controller_identifier}_{node_id}_{endpoint_id}_{entity_type}
```

Example: `zwave_12345678_5_0_light`

---

### 6. Performance Monitoring (`performance.py`)

**Purpose**: Track and report integration performance

**Key Features**:
- Method execution timing
- Call frequency tracking
- Slow call detection
- Duplicate call warnings
- Periodic reporting

**Key Components**:
```python
@track_performance                         # Decorator for timing
@log_call                                  # Decorator for logging
class PerformanceMonitor                   # Metrics aggregation
class CallTracker                          # Duplicate detection
```

**Usage**:
```python
@track_performance
async def my_method(self):
    # Automatically tracked
    pass
```

---

### 7. Setup Flow (`setup.py`)

**Purpose**: Initial configuration and controller discovery

**Key Responsibilities**:
- Z-Wave JS Server discovery (optional)
- URL validation
- Controller connection and identification
- Configuration generation

**Setup Steps**:
1. User enters Z-Wave JS Server URL
2. Driver connects and retrieves controller info
3. Configuration created with home_id as identifier
4. Friendly name generated from controller metadata
5. Configuration saved and returned

---

## Data Flow

### 1. Entity Registration Flow

```
Start Integration
    │
    ▼
Connect to Z-Wave JS Server
    │
    ▼
Get Controller Info
    │
    ▼
Query All Nodes
    │
    ▼
For Each Node:
    │
    ├─► Identify Command Classes
    │
    ├─► Determine Entity Type (light/cover/button)
    │
    ├─► Create Entity Instance
    │
    └─► Register with UC API
```

### 2. Command Flow (Turn On Light)

```
User Presses Button on Remote
    │
    ▼
UC API Sends Command
    │
    ▼
driver.handle_light_command()
    │
    ▼
bridge.control_light()
    │
    ▼
zwave_client.set_value()
    │
    ▼
WebSocket Message to Z-Wave JS Server
    │
    ▼
Z-Wave JS Server Sends Z-Wave Command
    │
    ▼
Z-Wave Device Receives & Executes
```

### 3. Update Flow (State Change)

```
Z-Wave Device State Changes
    │
    ▼
Z-Wave JS Server Detects Change
    │
    ▼
WebSocket Event: "value_updated"
    │
    ▼
zwave_client Receives Event
    │
    ▼
bridge._on_value_updated()
    │
    ▼
bridge.events.emit(UPDATE)
    │
    ▼
driver.on_device_update()
    │
    ▼
UC API Entity State Updated
    │
    ▼
Remote UI Reflects Change
```

### 4. Reconnection Flow (Watchdog)

```
Watchdog Timer Expires (30s)
    │
    ▼
Check WebSocket Connection
    │
    ├─► Connected? → Continue Monitoring
    │
    └─► Disconnected? ───┐
                         ▼
            Emit DISCONNECTED Event
                         │
                         ▼
            Attempt Reconnection
                         │
                         ├─► Success → Emit CONNECTED, Resume
                         │
                         └─► Failure → Wait & Retry
```

---

## Event System

### Internal Events (Bridge → Driver)

```python
EVENTS.CONNECTING         # Connection attempt started
EVENTS.CONNECTED          # Successfully connected
EVENTS.DISCONNECTED       # Connection lost
EVENTS.ERROR              # Error occurred
EVENTS.UPDATE             # Entity state updated
```

### Z-Wave Events (Z-Wave JS Server → Client)

```python
"value_updated"           # Node value changed
"node_status_changed"     # Node online/offline
"node_added"              # New node detected
"node_removed"            # Node removed
```

### UC API Events (Driver → Remote)

```python
EntityChange              # Entity state changed
ConnectionState           # Integration connected/disconnected
```

---

## Threading & Async Model

### Async Architecture
- All I/O operations are async (asyncio)
- WebSocket operations non-blocking
- Command execution concurrent
- Event handling asynchronous

### Event Loop
- Single event loop per integration
- Background tasks for watchdog
- Non-blocking entity updates

### Thread Safety
- All shared state protected
- Event handlers run in event loop
- No blocking operations in handlers

---

## Configuration Storage

### File Structure
```
config/
  └── devices/
      └── zwave_{home_id}/
          └── config.json
```

### Configuration Schema
```json
{
  "identifier": "zwave_12345678",
  "name": "Z-Wave Controller (Living Room)",
  "address": "ws://192.168.1.100:3000",
  "model": "Aeotec Z-Stick Gen5+",
  "home_id": "12345678",
  "sdk_version": "7.15.3",
  "library_version": "Z-Wave 7.0"
}
```

---

## Error Handling Strategy

### Connection Errors
- Automatic retry with exponential backoff
- Watchdog recovery for dropped connections
- Event emission for UI feedback

### Command Errors
- Timeout detection (default 5s)
- Error propagation to UC API
- Detailed logging

### State Errors
- Graceful degradation
- State validation
- Recovery attempts

---

## Performance Considerations

### Optimizations
- Lazy entity loading
- Efficient WebSocket message handling
- Minimal polling (event-driven)
- Connection pooling ready

### Bottlenecks
- Z-Wave network latency
- WebSocket round-trip time
- Large network enumeration

### Monitoring
- Performance tracking on all operations
- Slow call warnings (>1s)
- Call frequency analysis
- Periodic reports

---

## Security Considerations

### Network Security
- WebSocket connections (ws://)
- No authentication to Z-Wave JS Server (local network)
- Consider using wss:// for remote access

### Access Control
- Integration runs with user privileges
- No direct Z-Wave protocol access
- Mediated through Z-Wave JS Server

### Data Privacy
- No cloud communication
- All operations local
- Configuration stored locally

---

## Scalability

### Current Limits
- Single controller per configuration
- Tested with 50+ devices
- Suitable for residential installations

### Scaling Considerations
- Multiple controllers: Create multiple configurations
- Large networks: Consider Z-Wave mesh optimization
- High-frequency updates: Performance monitoring helps identify issues

---

## Future Architecture Enhancements

### Planned Improvements
1. **Real-time Entity Management**
   - Dynamic add/remove as network changes
   - Hot-reload capability

2. **Multi-Controller Support**
   - Unified entity management
   - Cross-controller scenes

3. **Advanced Caching**
   - Node capability caching
   - State prediction
   - Reduced Z-Wave queries

4. **Health Monitoring**
   - Network quality metrics
   - Device health indicators
   - Performance dashboards

5. **Advanced Features**
   - Scene management
   - Association configuration
   - Firmware updates
   - Network healing

---

## Development Guidelines

### Adding New Entity Types

1. Create entity file (e.g., `sensor.py`)
2. Define entity class with UC API attributes
3. Implement command handlers
4. Add to `const.py` entity definitions
5. Update `bridge.py` with query methods
6. Update `driver.py` with registration logic

### Adding New Commands

1. Define command in entity class
2. Implement handler in entity file
3. Add bridge method for Z-Wave communication
4. Update driver command routing
5. Add performance tracking
6. Test thoroughly

### Debugging

1. Enable detailed logging
2. Use performance tracking decorators
3. Check watchdog status
4. Review WebSocket messages
5. Verify Z-Wave JS Server logs

---
