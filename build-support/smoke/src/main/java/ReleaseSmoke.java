import com.mgmtp.a12.kernel.md.model.a12internal.fieldtypes.BooleanType;
import com.mgmtp.a12.kernel.md.model.a12internal.fieldtypes.NumberType;
import com.mgmtp.a12.kernel.md.model.a12internal.fieldtypes.DateType;
import com.mgmtp.a12.kernel.md.model.a12internal.fieldtypes.DateRangeType;
import com.mgmtp.a12.kernel.md.structuralmapping.internal.consistency.SMMFieldTypeCheckUtils;
import com.mgmtp.a12.kernel.md.combination.a12internal.KernelModelsWorkspaceConverter;
import com.mgmtp.a12.dataservices.wcf.WorkspaceFactory;

public final class ReleaseSmoke {
    public static void main(String[] args) {
        if (!SMMFieldTypeCheckUtils.isFieldTypeAssignable(new BooleanType(), new BooleanType()))
            throw new AssertionError("Boolean must map to Boolean");
        if (SMMFieldTypeCheckUtils.isFieldTypeAssignable(new NumberType(), new BooleanType()))
            throw new AssertionError("Number must not map to Boolean");
        if (!SMMFieldTypeCheckUtils.isFieldTypeAssignable(new DateType(), new DateType()))
            throw new AssertionError("Matching date formats and precision must be assignable");
        var range = DateRangeType.builder().format("yyyy-MM-dd").build();
        if (!SMMFieldTypeCheckUtils.isFieldTypeAssignable(range, range))
            throw new AssertionError("Matching date ranges and year interpretation must be assignable");
        var workspace = WorkspaceFactory.getInstance().createWorkspace();
        var converted = new KernelModelsWorkspaceConverter(n -> {
            throw new AssertionError("Unexpected conversion notification: " + n);
        }).convert(workspace);
        if (!converted.getModels().isEmpty()) throw new AssertionError("Empty workspace changed");
        System.out.println("PASS: structural mapping accepts compatible types and rejects incompatible types; workspace conversion works.");
    }
}
