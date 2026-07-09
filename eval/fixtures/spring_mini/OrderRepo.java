package app.data;

public class OrderRepo {
    public String save() {
        return write();
    }

    public String find() {
        return read();
    }

    private String write() {
        return "written";
    }

    private String read() {
        return "read";
    }
}
